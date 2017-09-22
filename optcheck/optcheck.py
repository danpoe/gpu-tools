#!/usr/bin/env python3

# Check a CUDA binary for optimisations

# ------------------------------------------------------------------------------

import sys
import os
import subprocess
import re
import enum

# ------------------------------------------------------------------------------
# Generic globals

debug = False
cmd = "optcheck"
binary = ""
txt = ""

# Pre-maxwell or maxwell format
class Cfg(enum.IntEnum):
  pre_ma = 0
  ma = 1

cfg = Cfg.pre_ma

# ------------------------------------------------------------------------------
# Mappings

# Internal spec format (for one thread; in order):
# [(line-num, index, link register), ...]
#
# line-num: number of the instruction in the SASS output limited to instructions
# index: index into the instruction map (imap)
# link register: - 

# Spec instruction (for both loads and stores)
sins = ["IADD32I", "LOP32I.XOR"]

# Constant mapping (describes a SASS instruction), pre-maxwell:
# Index -> (SASS instruction, link register position, memory access indicator)
# The memory access indicator specifies whether the link register is part of a
# memory access
imap_pm = [
(["ST.E"], 0, 1), # 00, st.ca
(["LD.E"], 0, 0), # 01, ld.ca
(["ST.E.CG", "ST.E.CG.S"], 0, 1), # 02, st.cg
(["LD.E.CG", "LD.E.CG.S"], 0, 0), # 03, ld.cg
(["STS"], 0, 1), # 04, st.shared
(["LDS"], 0, 0), # 05, ld.shared
(["ATOM.E.CAS"], 0, 0), # 06, atom.cas
(["ATOM.E.EXCH", "ATOM.E.INC"], 0, 0),  # 07, atom.exch
(["ST.E.WT"], 0, 1), # 08, st.cv
(["LD.E.CV"], 0, 0)  # 09, ld.cv
]

# Same as above for maxwell
imap_ma = [
(["ST.E"], 0, 1), # 00, st.ca
(["LD.E"], 0, 0), # 01, ld.ca
(["ST.E", "ST.E.S"], 0, 1), # 02, st.cg
(["LD.E", "LD.E.S"], 0, 0), # 03, ld.cg
(["STS"], 0, 1), # 04, st.shared
(["LDS"], 0, 0), # 05, ld.shared
(["ATOM.E.CAS"], 0, 0), # 06, atom.cas
(["ATOM.E.EXCH", "ATOM.E.INC"], 0, 0),  # 07, atom.exch
(["ST.E"], 0, 1), # 08, st.cv
(["LD.E"], 0, 0), # 09, ld.cv
]

# Default is pre-maxwell
imap = imap_pm

# ------------------------------------------------------------------------------
# Internal

fl = ['membar.cta', 'membar.gl', 'membar.sys']
target = dict()
source = dict()
for f in fl:
  source[f] = 0
  target[f] = 0

# ------------------------------------------------------------------------------

def isspecn(num):
  return ((num & 0xffff0000) >> 16) == 0x7f3a

def getordn(num):
  return (num & 0x000000f0) >> 4

def gettypn(num):
  return (num & 0x0000ff00) >> 8

# ------------------------------------------------------------------------------

def print_err(s):
  print(s, file = sys.stderr)

def bail_err(s, print_usage = False):
  print_err(cmd + ": " + s)
  if print_usage:
    print_err("")
    usage()
  sys.exit(1)

def usage():
  print_err("Usage:")
  print_err("  optcheck.py [-debug] [-checkreg <bool>] [-mapping <map>]\
 (-bin <cubin> | -txt <txtfile>)")
  print_err("")
  print_err("  <bool>: indicating whether same register check is performed\
 (default true)")
  print_err("  <map>: select mapping, values 'pre-maxwell' (default) or\
 'maxwell'")
  print_err("  <cubin>: CUDA binary")
  print_err("  <txtfile>: text file containing cuobjdump output")
  print_err("")
  print_err("  Exit code: 0 (no opt detected), 1 (error), 2 (opt detected)")

def handle_args(args):
  global cmd
  global binary
  global txt
  global debug
  global cfg
  global imap
  global imap_pm
  global imap_ma

  cmd = args[0]
  l = len(args)
  if not (3 <= l <= 6):
    bail_err("Wrong number of arguments", True)

  next_is_bin = False
  next_is_txt = False
  next_is_map = False

  for i in range(1, l):
    arg = args[i]

    if next_is_bin:
      binary = arg
      next_is_bin = False
      continue
    if next_is_txt:
      txt = arg
      next_is_txt = False
      continue
    if next_is_map:
      if arg == "pre-maxwell":
        cfg = Cfg.pre_ma
        imap = imap_pm
      elif arg == "maxwell":
        cfg = Cfg.ma
        imap = imap_ma
      else:
        bail_err("invalid argument to -mapping", True)
      next_is_map = False
      continue

    if arg == "-bin":
      next_is_bin = True
    elif arg == "-txt":
      next_is_txt = True
    elif arg == "-mapping":
      next_is_map = True
    elif arg == "-debug":
      if debug:
        bail_err("-debug given more than once", True)
      debug = True
    elif arg == "-checkreg":
      bail_err("Option -checkreg currently unimplemented; check is always\
 performed", True)
    else:
      bail_err("Unknown option '" + arg + "'", True)

  if next_is_bin or next_is_txt:
    bail_err("No argument to -bin or -txt provided", True)

  if not binary and not txt:
    bail_err("Neither binary nor textfile given", True)

# ------------------------------------------------------------------------------

### Skip over nested items (return pos of next character), forwards or backwards
# s: file as string
# a: left item
# b: right item
# d: direction(1: forward, -1: backward)
# pos: points at first item (a for forward, b for backward)
def skip_nested(s, a, b, d, pos):
  l = len(s)
  assert(pos < l)
  assert(pos >= 0)

  assert(d == -1 or d == 1);

  al = len(a)
  bl = len(b)
  assert(d != 1 or s[pos:al] == a);
  assert(d != -1 or s[pos:bl] == b);

  cnt = d
  pos += d
  while True:
    assert(pos >= 0)
    assert(pos < l)
    if s[pos:al] == a:
      cnt += 1
    elif s[pos:bl] == b:
      cnt -= 1

    if cnt == 0:
      assert(pos >= 0)
      assert(pos < l)
      return pos

    pos += d

  assert(False)

### Return position of current or next non-whitespace character
def eat(s, pos):
  l = len(s)
  assert(pos < l)
  while (pos < l):
    c = s[pos]
    if c != ' ' and c != '\t' and c != '\n':
      return pos
    pos += 1
  assert(False)
  return pos

# ------------------------------------------------------------------------------
# Retrieve spec in internal format

def isspeccand(s):
  global sins
  for spec in sins:
    if s.startswith(spec):
      return True
  return False

### Split spec instruction (add or xor)
# 1: spec instruction string
def split_add_inst(ins):
  global sins
  ins = ins.strip()
  ins = ins.rstrip(";")

  sw = False
  for spec in sins:
    if ins.startswith(spec):
      ins = ins.replace(spec, "", 1)
      sw = True
      break
  assert(sw)

  items = ins.split(",")
  assert(len(items) == 3)
  reg = items[1].strip()
  num = items[2].strip()
  return (int(num, 16), reg)

### Get spec values
# 1: instruction (string)
def get_spec_item(ins):
  if not isspeccand(ins):
    return None
  spec = split_add_inst(ins)
  num = spec[0]
  reg = spec[1]
  if not isspecn(num):
    return None
  order = getordn(num)
  typ = gettypn(num)
  return (typ, order, reg)

### Retrieve spec in internal format
# 1: list of instructions (strings) in static program order
def cluster_specs(lis):
  n = len(lis)
  cl = []

  assert(n > 5)

  # Find spec items with order specifier 0
  for i in range(0, n):
    ins = lis[i]
    r = get_spec_item(ins)
    if not r:
      continue
    typn, ordn, regn = r
    assert(0 <= typn < len(imap))
    if ordn != 0:
      continue
    cl += [[(i, typn, regn)]]

  # Exit if no items with the 0 order specifier have been found
  cll = len(cl)
  if cll == 0:
    bail_err("No specification found")

  # Associate next spec items with closest cluster containing an order
  # predescessor
  i = 1
  last_found = True
  while last_found:
    last_found = False
    # Iterate over instructions
    for j in range(0, n):
      ins = lis[j]
      r = get_spec_item(ins)
      if not r:
        continue
      typn, ordn, regn = r
      assert(0 <= typn < len(imap))
      if ordn != i:
        continue
      # Spec item with order specifier i found
      last_found = True
      m = sys.maxsize
      cl_idx = -1
      # Find closest cluster
      for k in range(0, cll):
        item = cl[k]
        l = len(item)
        if l != i:
          continue
        last = item[i-1]
        d = abs(last[0] - j)
        if d < m:
          m = d
          cl_idx = k
      if cl_idx == -1:
        bail_err("Missing item in order specification")
      item = cl[cl_idx]
      item += [(j, typn, regn)]
      cl[cl_idx] = item
    i += 1

  # Look for gaps (sanity check)
  for j in range(0, n):
    ins = lis[j]
    r = get_spec_item(ins)
    if not r:
      continue
    typn, ordn, regn = r
    assert(0 <= typn < len(imap))
    if ordn >= i:
      bail_err("Order gap in specification")

  return cl

# ------------------------------------------------------------------------------
# Check spec:
# 1. Retrieve specification (in internal format)
# 2. Check specification

def isinst(s):
  return re.match('^\s+/\*.*[^0-9a-fxA-FX/\* ]', s)

# op: memory access operand, like [r1]
def get_mem_reg(op):
  assert(type(op) == str)
  op = op.strip()
  op = op.lstrip('[')
  op = op.rstrip(']')
  op = op.strip()
  if re.match("^[rR][0-9]+$", op):
    return op
  else:
    return None

# ins: full instruction, oc: opcode list
def split_mem_inst(ins, ocl):
  global cfg
  assert(type(ins) == str)
  assert(type(ocl) == list)

  for oc in ocl:
    if has_oc(ins, oc):
      ins = ins[len(oc):]
      break
  else:
    assert(False)

  ins = ins.strip()
  ins = ins.rstrip(";")

  items = ins.split(",")
  items = [ins.strip() for ins in items]
  return items

# ins: full instruction, oc: opcode
def has_oc(ins, oc):
  if ins[0:len(oc)+1] == oc + " ":
      return True
  return False

# ins: full instruction, ocl: opcode list
def has_ocl(ins, ocl):
  for oc in ocl:
    if has_oc(ins, oc):
      return True
  return False

### Check a single cluster
# 1: specification for a single thread
# 2: list of instructions
def check(spec, lis):
  global fl
  global source

  l = len(spec)
  ll = len(lis)
  assert(l > 0)
  assert(ll > 5)

  # Window size
  w_top_sz = 40
  w_bot_sz = 8

  # First instruction
  ln, idx, reg =  spec[0]
  assert(0 <= idx < len(imap))
  # SASS instruction, link register position, memory access indicator
  ocl, lrp, mai = imap[idx]

  w_top = max(ln - w_top_sz, 0)
  w_bot = min(ln + w_bot_sz, ll)

  # Index of next specification item
  next = 1

  # Index of first instruction
  first = 0

  # Check all instructions in the window
  for i in range(w_top, w_bot):
    ins = lis[i]
    # Swallow predicate
    ins = re.sub(r'@[!a-zA-Z0-9]+\s+', '', ins, count=1)
    # Check for SASS instruction name
    if has_ocl(ins, ocl):
      # Check for instruction register
      regs = split_mem_inst(ins, ocl)
      r = regs[lrp]
      if mai:
        r = get_mem_reg(r)
        if not r:
          continue
      if r == reg:
        if next == 1:
          first = i
        # Check if all specification items have been handled   
        if next >= l:
          # Count fences
          for j in range(first+1, i):
            ins = lis[j].lower()
            for f in fl:
              if f in ins:
                source[f] += 1
          return True
        # Next specification item for subsequent iterations
        ln, idx, reg = spec[next]
        ocl, lrp, mai = imap[idx]
        next += 1

  return False

# 1: cubobjdump output
def check_spec(s):
  lis = s.splitlines()
  lis = list(filter(isinst, lis))
  n = len(lis)
  assert(n > 5)

  for i in range(0, n):
    ln = re.sub("/\*[^*/]*\*/", "", lis[i])
    ln = ln.strip()
    lis[i] = ln

  cl = cluster_specs(lis)
  l = len(cl)
  assert(l > 0)

  print("Specification clusters: " + str(l))
  print("Specification: " + str(cl))

  ok = True
  i = 0
  # For each cluster
  for spec in cl:
    ret = check(spec, lis)
    if ret:
      print("Cluster " + str(i) + ": OK")
    else:
      print("Cluster " + str(i) + ": Failure")
    i += 1
    ok &= ret

  return ok

# ------------------------------------------------------------------------------

if __name__ == "__main__":
  handle_args(sys.argv)
  out = ''
  testname = ''

  if binary:
    if not os.path.isfile(binary):
      bail_err("CUDA binary does not exist")
    try:
      out = subprocess.check_output(["cuobjdump", "-sass", binary],
                                    stderr = subprocess.STDOUT,
                                    universal_newlines = True)
    except OSError:
      bail_err("cuobjdump error (OSError)")
    except subprocess.CalledProcessError:
      bail_err("cuobjdump error (CalledProcessError)")
    print("Binary '" + binary + "' successfully loaded")
    testname = binary
  elif txt:
    sf = open(txt, 'r')
    out = sf.read()
    sf.close()
    print("File '" + txt + "' successfully read")
    testname = txt
  else:
    assert(False)

  # Compute target
  testname = testname.lower()
  for f in fl:
    c = testname.count(f + 's')
    target[f] += 2 * c
  for f in fl:
    c = testname.count(f)
    target[f] += (c - target[f] / 2)

  ret = check_spec(out)

  # Check source against target
  for f in fl:
    if target[f] > source[f]:
      ret = False
      break

  if ret:
    print("!!SUCCESS!!")
  else:
    print("!!FAILURE!!")
    sys.exit(2)

