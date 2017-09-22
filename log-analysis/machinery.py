import argparse
import re
import sys
import os
import inspect
import enum
import pickle
import collections
import pyparsing as pp
import traceback
from functools import reduce

from generic import convert, lty, interleave, listify

# ------------------------------------------------------------------------------
# Error handling

cmd = '-'

def print_err(s):
  print(s, file=sys.stderr)

# et: type, ei: value, to: traceback
def exception_handler(et, ei, to):
  global cmd
  print_err(cmd + ': error: ' + str(ei))
  print_err('##### Backtrace #####')
  traceback.print_tb(to)
  print_err('  Exception: ' + str(et))

def setup_err_handling(c):
  global cmd
  cmd = c
  sys.excepthook = exception_handler

class ErrMsg(enum.IntEnum):
  logform = 0

def chk(c, msg):
  global cmd
  if c:
    return

  # Predefined error messages
  m = [""] * 1
  m[ErrMsg.logform] = "litmus log format error"

  # Get call site info
  frame_list = inspect.stack()
  assert(len(frame_list) > 1)
  frame = frame_list[1]
  f = frame[1]
  f = os.path.basename(f)
  ln = frame[2]
  # Print error message
  if type(msg) is ErrMsg:
    msg = m[msg]
  assert(type(msg) is str)
  print_err(cmd + ': error (at ' + f + ':' + str(ln) + '): ' + msg)
  sys.exit(1)

def bail(msg):
  chk(False, msg)

# ------------------------------------------------------------------------------
# Working with several logs

### Get input
# Takes: 
# - list of filenames (litmus logs or pickles), may be singleton list if only
#   one input file is requested;
# - the optional arguments only have an effect when a textual litmus log is
#   given
# Returns: list of Log objects
def get_logs(fs, lh, fix_names=False, drop_dups=False, drop_numeric=False):
  fs = listify(fs)
  assert(len(fs) > 0)
  l = list()
  for f in fs:
    try:
      log = unpickle(f)
      log.verify()
      chk(type(log) == lh, 'wrong log type (maybe use -i)')
      print('unpickled file ' + f)
    except OSError:
      raise
    except Exception:
      # Cannot unpickle file as it may be a textual log
      log = lh()
      print('opening file ' + f + ' as textual litmus log')
      log.from_file(f, fix_names, drop_dups, drop_numeric)
      log.verify()
    l.append(log) 
  return l

### Get entry from first log that has key
def get_entry(key, logs):
  logs = listify(logs)
  assert(len(logs) > 0)
  for log in logs:
    le = log.get(key)
    if le:
      return le
  assert(False)

# ------------------------------------------------------------------------------
# Helper functions

# Parse action for determining e.g. is_cta()
def f1(tokens):
  for t in tokens:
    if t == False:
      return t
  if len(tokens) > 1:
    return False
  return True

# Parse action for determining e.g. is_cta()
def f2(tokens):
  for t in tokens:
    if t == False:
      return t
  if len(tokens) < 2:
    return False
  return True

# ------------------------------------------------------------------------------
# Get key sets

### Get keys over all logs in list
def get_keys(logs):
  logs = listify(logs)
  ks = map(lambda log: [x for x in log.d.keys()], logs)
  ks = reduce(lambda a, b: list(set(a + b)), ks, [])
  ks.sort()
  return ks

### Return keys over all logs matching a regular expression
def get_matching_keys(regexes, logs, ks=None):
  logs = listify(logs)
  if ks == None:
    ks = get_keys(logs)
  l = [] 
  for k in ks:
    for r in regexes:
      if re.match(r, k):
        l.append(k)
        break
  return l

### Get keys with filter function applied to all log entries
def get_filtered_keys(filt, logs, ks=None):
  logs = listify(logs)
  if ks == None:
    ks = get_keys(logs)
  l = []
  for k in ks:
    e = get_entry(k, logs)
    if filt(e):
      l.append(k)
  return l

### Get positive keys
def get_pos_keys(logs, ks=None):
  logs = listify(logs)
  if ks == None:
    ks = get_keys(logs)
  l = []
  for k in ks:
    for log in logs:
      e = log.get(k)
      if e and e.is_pos():
        l.append(k)
        break
  return l

# ------------------------------------------------------------------------------
# Pickle

def unpickle(f):
  f = open(f, "rb")
  b = pickle.load(f)
  f.close()
  return b

def gherkin(log, f):
  f = open(f, "wb")
  pickle.dump(log, f)
  f.close()

# ------------------------------------------------------------------------------
# Parsing, processing, and printing a single log entry

# Thrown during parsing if litmus test has a numeric name (e.g. *003)
class NumericNameError(Exception):
  def __init__(self, name):
    self.name = name
  def __repr__(self):
    return self.name

# Thrown when log entry does not match the parsing regex
class InvalidEntryError(Exception):
  def __init__(self, entry):
    self.entry = entry
  def __repr__(self):
    return self.entry

# Thrown if log entry corresponds to a failed litmus test (e.g. GPUAssert
# failed)
class FailureEntryError(Exception):
  def __init__(self, entry):
    self.entry = entry
  def __repr__(self):
    return self.entry

# Thrown if two tests are inconsistent (e.g. have different scope trees). Can
# happen if e.g. logs are compared and tests are matched up according to name.
class InconsistentTestsError(Exception):
  def __init__(self, s):
    self.s = s
  def __repr__(self):
    return self.s

class LogEntry:
  """Entry in a litmus log corresponding to a successful test"""

  # Normalize memory region designator (for use in unique names)
  mem_norm = {'g': 'g', 's': 's', 'l': 's',
              'global': 'g', 'shared': 's', 'local': 's'}

  def __init__(self, s, parent=""):

    self.raw = ""
    self.raw_fixed = ""
    self.name = ""
    # Name without scope and memory region designator
    self.short_name = ""
    # Set to name currently
    self.kind = ""

    self.scopetree = ""
    # List of pairs of string: [(x, global), (y, shared), ...]
    self.memorymap = []

    # Frequencies
    self.pos = 0
    self.neg = 0
    self.total = 0

    # Incantations
    self.general_bc = False
    self.mem_stress = False
    self.rand_threads = False
    self.barrier = False

    # Link to the log this entry is part of (string name)
    self.parent = parent

    self.parse(s)

  def __repr__(self):
    #return self
    return self.name

  def __cmp__(self, other):
    if self.name < other.name:
      return -1
    elif self.name == other.name:
      return 0
    else:
      return 1

  def check_const(self, e):
    if self.name != e.name:
      raise InconsistentTestsError('Name')
    if self.short_name != e.short_name:
      raise InconsistentTestsError('Short name')
    if self.kind != e.kind:
      raise InconsistentTestsError('Kind')
    if self.scopetree.strip() != e.scopetree.strip():
      raise InconsistentTestsError('Scopetree')
    if self.memorymap != e.memorymap:
      raise InconsistentTestsError('Memorymap')

  def is_pos(self):
    return self.pos > 0

  ############################
  # Parsing - Extract fields #
  ############################

  def get_name(self, s):
    r = r'[ \t]*(GPU_PTX|RACE_OPENCL)[ \t]+(?P<name>[^\s]+)[ \t]*'
    mo = re.fullmatch(r, s)
    if not mo:
      return False, ''
    d = mo.groupdict()
    return True, d['name']

  def get_st(self, s):
    mo = re.search(r'\([ \t]*device', s)
    if not mo:
      return False, ''
    return True, s.strip()

  def get_mm(self, s):
    item = r'([a-zA-Z]+[ \t]*:[ \t]*(global|shared|local))'
    mo = re.fullmatch(item + r'([ \t]*(,|;)[ \t]*' + item + r')*', s)
    if not mo:
      return False, []
    trans = str.maketrans(',', ';')
    m = s.strip()
    m = m.translate(trans)
    l = m.split(';')
    m = list()
    for el in l:
      el = el.split(':')
      var = el[0].strip()
      assert(len(var) == 1)
      assert(var.isalpha())
      space = el[1].strip().replace('local', 'shared')
      assert(space in ['global', 'shared'])
      m.append((var, space))
    m.sort(key=lambda p: p[0])
    return True, m

  def get_nums(self, s):
    a = r'[ \t]*[Pp]ositive:[ \t]*(?P<pos>[0-9]+)[ \t]*,?'
    b = r'[ \t]*[Nn]egative:[ \t]*(?P<negx>[0-9]+)[ \t]*'
    mo = re.fullmatch(a + b, s)
    if not mo:
      return False, (0, 0)
    d = mo.groupdict()
    return True, (int(d['pos']), int(d['negx']))

  def get_mem_stress(self, s):
    r = r'/\*[ \t]*gpu_mem_stress[ \t]*:[ \t]*(?P<b>(true|false))'
    mo = re.search(r, s)
    if not mo:
      return False, False
    d = mo.groupdict()
    return True, 'true' in d['b']

  def get_general_bc(self, s):
    r = r'/\*[ \t]*gpu_general_bc[ \t]*:[ \t]*(?P<b>(true|false))'
    mo = re.search(r, s)
    if not mo:
      return False, False
    d = mo.groupdict()
    return True, 'true' in d['b']

  def get_barrier(self, s):
    r = r'/\*[ \t]*barrier[ \t]*:[ \t]*(?P<b>(none|user))'
    mo = re.search(r, s)
    if not mo:
      return False, False
    d = mo.groupdict()
    return True, 'user' in d['b']

  def get_rand_threads(self, s):
    r = r'/\*[ \t]*gpu[_-]rand[_-]threads[ \t]*:[ \t]*(?P<b>(true|false))'
    mo = re.search(r, s)
    if not mo:
      return False, False
    d = mo.groupdict()
    return True, 'true' in d['b']

  ### Collect items from string
  # s: log as string
  # fl: parsing function list
  def collect(self, s, fl):
    le = len(fl)
    key, f = fl[0]
    lines = s.splitlines()
    i = 0
    res = dict()
    for l in lines:
      r = f(l)
      if r[0]:
        res[key] = r[1]
        i += 1
        if i == le:
          break
        key, f = fl[i]
    lm = len(res)
    if lm == le:
      return res
    return False

  ### Extract fields from log
  def extract(self, s):
    fl1 = [('name', self.get_name), ('st', self.get_st), ('mm', self.get_mm),
           ('nums', self.get_nums)]
    fl2 = fl1 + [('barrier', self.get_barrier),
                 ('general_bc', self.get_general_bc),
                 ('mem_stress', self.get_mem_stress),
                 ('rand_threads', self.get_rand_threads)]

    try_list = [fl2, fl1]

    for fl in try_list:
      d = self.collect(s, fl)
      if d:
        break
    else:
      mo = re.search('([Ff]ail)|([Aa]ssert)|([Ee]rror\:)', s)
      if mo:
        raise FailureEntryError(s)
      raise InvalidEntryError(s)
    
    return d

  ##################
  # Parsing - Main #
  ##################

  ### Parse log entry, create derived entries, and perform semantical checks
  # Throws: NumericNameError, InvalidEntryError, FailureEntryError
  def parse(self, s):

    d = self.extract(s)

    name = d['name']
    self.name = name
    # Strip off suffix after '-'
    self.short_name = self.get_short_name(name)
    assert(len(self.name) >= len(self.short_name))

    num = re.fullmatch('[0-9]{3}', name[-3:])
    if num:
      raise NumericNameError(name)

    self.kind = name

    self.raw = s

    st = d['st']
    self.scopetree = st
    # No parse actions necessary here, just a syntax check
    def f(x): return x
    p = self.get_st_parser([f, f, f ,f, f])
    pr = p.parseString(st)
    chk(pr, ErrMsg.logform)

    nums = d['nums']
    self.pos = nums[0]
    assert(self.pos >= 0)
    self.neg = nums[1]
    assert(self.neg >= 0)
    total = self.pos + self.neg
    self.total = total

    self.memorymap = d['mm']

    self.general_bc = d.get('general_bc', False)
    self.mem_stress = d.get('mem_stress', False)
    self.rand_threads = d.get('rand_threads', False)
    self.barrier = d.get('barrier', False)

  # For debugging
  def dump(self):
    s =\
    'Internal fields:\n' +\
    '  Name: ' + self.name + '\n' +\
    '  Short name: ' + self.short_name + '\n' +\
    '  Kind: ' + self.kind + '\n' +\
    '  Scope tree: ' + self.scopetree + '\n' +\
    '  Memory map: ' + str(self.memorymap) + '\n' +\
    '  Positive: ' + str(self.pos) + '\n' +\
    '  Negative: ' + str(self.neg) + '\n' +\
    '  Total: ' + str(self.total) + '\n' +\
    'Scope and Mem Predicates:' + '\n' +\
    '  is_global: ' + str(self.is_global()) + '\n' +\
    '  is_shared: ' + str(self.is_shared()) + '\n' +\
    '  is_mixed_mem: ' + str(self.is_mixed_mem()) + '\n' +\
    '  is_mixed_scope: ' + str(self.is_mixed_scope()) + '\n' +\
    '  is_thread: ' + str(self.is_thread()) + '\n' +\
    '  is_warp: ' + str(self.is_warp()) + '\n' +\
    '  is_cta: ' + str(self.is_cta()) + '\n' +\
    '  is_ker: ' + str(self.is_ker()) + '\n' +\
    '  is_dev: ' + str(self.is_dev()) + '\n' +\
    'Incantation predicates:' + '\n' +\
    '  is_mem_stress: ' + str(self.is_mem_stress()) + '\n' +\
    '  is_general_bc: ' + str(self.is_general_bc()) + '\n' +\
    '  is_rand_threads: ' + str(self.is_rand_threads()) + '\n' +\
    '  is_barrier: ' + str(self.is_barrier()) + '\n' +\
    'Pretty printers:' + '\n' +\
    '  ppi_memorymap: ' + str(self.ppi_memorymap()) + '\n' +\
    '  ppi_memorymap_name: ' + str(self.ppi_memorymap_name()) + '\n' +\
    '  ppi_scopetree_name: ' + str(self.ppi_scopetree_name()) + '\n' +\
    '  pp_scopetree: ' + str(self.pp_scopetree())
    return s

  # Give test a wacky name for use as a key (and possibly strip off existing
  # name suffixes); also fix raw litmus log (instance variable raw_fixed)
  #
  # Example names to be fixed:
  # - 2+2W+membar.cta+membar.sys
  # - IRIW+addr+po
  # - IRIW+membar.cta+membar.gl-p0p1.p2p3-xgyg
  # Do not fix but report as errors:
  # - 3.2W002
  def fix_name(self):
    name = self.name
    name_orig = name
    idx = name.find('-')
    if idx != -1:
      chk(re.search('[Pp]0', name), 'test name contains dash (-) yet no p0')
      name = name[:idx]
    # Fix test name
    self.short_name = name
    name += '-' + self.ppi_scopetree_name() + '-' + self.ppi_memorymap_name()
    self.name = name
    # Fix raw log
    raw = self.raw

    self.raw_fixed = raw
    raw1 = re.sub(r'GPU_PTX\s+' + re.escape(name_orig), 'GPU_PTX ' +
      name, raw)
    if raw1 != raw:
      self.raw_fixed = raw1
    raw2 = re.sub(r'RACE_OPENCL\s+' + re.escape(name_orig), 'RACE_OPENCL ' +
      name, raw)
    if raw2 != raw:
      self.raw_fixed = raw2
    assert(raw == raw1 or raw == raw2)

  def get_short_name(self, name):
    idx = name.find('-')
    if idx != -1:
      chk(re.search('[Pp]0', name), 'test name contains dash (-) yet no p0')
      return name[:idx]
    return name

  # Produce scope tree parser using a list of parse actions (can be used to e.g.
  # translate a scope tree to a different format)
  def get_st_parser(self, l):

    # Tokens
    d = pp.Suppress('device')
    k = pp.Suppress('kernel')
    c = pp.Suppress('cta')
    w = pp.Suppress('warp')
    t = pp.Regex('[Pp][0-9]+')
    lp = pp.Suppress('(')
    rp = pp.Suppress(')')

    # Grammar
    wn = lp + w + pp.OneOrMore(t) + rp
    cn = lp + c + pp.OneOrMore(wn) + rp
    kn = lp + k + pp.OneOrMore(cn) + rp
    dn = lp + d + pp.OneOrMore(kn) + rp
    st = pp.OneOrMore(dn)

    # Parse actions
    wn.setParseAction(l[0])
    cn.setParseAction(l[1])
    kn.setParseAction(l[2])
    dn.setParseAction(l[3])
    st.setParseAction(l[4])

    return st

  # Example ID: gtx540-2+2W+membar.cta+membar.sys-p0:p1-xgyg.txt
  def get_id(self):
    assert(self.parent)
    p = self.parent
    p = os.path.basename(p)
    # Strip off suffix if parent has one (e.g. gtx660.txt)
    idx = p.find('.')
    if idx != -1:
      p = p[:idx]
    s = p + '-' + self.name
    return s

  def store_log(self, fn=None):
    if not fn:
      fn = 'entries/' + self.get_id() + '.txt'
    f = open(fn, 'w')
    f.write(self.raw)
    f.close()

  def store_log_dir(self, di):
    fn = di + '/' + self.get_id() + '.txt'
    f = open(fn, 'w')
    f.write(self.raw)
    f.close()  

  #####################
  # Memory Predicates #
  #####################

  def is_global(self):
    for el in self.memorymap:
      if el[1] != "global":
        return False
    return True

  def is_shared(self):
    for el in self.memorymap:
      if el[1] != "shared" and el[1] != "local":
        return False
    return True

  def is_mixed_mem(self):
    return not (self.is_global() or self.is_shared())

  ####################
  # Scope predicates #
  ####################

  # s-warp
  def is_thread(self):
    l = [f2, f1, f1, f1, f1]
    p = self.get_st_parser(l)
    pr = p.parseString(self.scopetree)
    return bool(pr[0])

  # d-warp:s-cta
  def is_warp(self):
    l = [f1, f2, f1, f1, f1]
    p = self.get_st_parser(l)
    pr = p.parseString(self.scopetree)
    return bool(pr[0])

  # d-cta:s-ker
  def is_cta(self):
    l = [f1, f1, f2, f1, f1]
    p = self.get_st_parser(l)
    pr = p.parseString(self.scopetree)
    return bool(pr[0])

  # d-ker:s-dev
  def is_ker(self):
    l = [f1, f1, f1, f2, f1]
    p = self.get_st_parser(l)
    pr = p.parseString(self.scopetree)
    return bool(pr[0])

  # d-dev
  def is_dev(self):
    l = [f1, f1, f1, f1, f2]
    p = self.get_st_parser(l)
    pr = p.parseString(self.scopetree)
    return bool(pr[0])

  # mixed
  def is_mixed_scope(self):
    return not (self.is_thread() or self.is_warp() or self.is_cta() or
      self.is_ker() or self.is_dev())

  ##########################
  # Incantation predicates #
  ##########################

  def is_general_bc(self):
    return self.general_bc

  def is_mem_stress(self):
    return self.mem_stress

  def is_rand_threads(self):
    return self.rand_threads

  def is_barrier(self):
    return self.barrier

  ####################
  # Other predicates #
  ####################

  def does_match(self, rl):
    assert(lty(rl, str))
    for r in rl:
      if re.match(r, self.name):
        return True
    return False

  # Match against the short name (without scope tree and memory map designator)
  def simple_match(self, s):
    assert(type(s) == str)
    if self.short_name.lower() == s.lower():
      return True
    return False

  ###################
  # Pretty printers #
  ###################

  # Internal (non-HTML) pretty printers

  def ppi_memorymap(self):
    s = ""
    n = len(self.memorymap)
    for i in range(0, n):
      el = self.memorymap[i]
      s += el[0] + ': ' + el[1]
      if i < n-1:
        s += ', '
    return s

  ## pp for name as key
  def ppi_memorymap_name(self):
    s = ""
    for el in self.memorymap:
      s += el[0] + self.mem_norm[el[1]]
    return s

  # pp for name as key
  def ppi_thread_name(self, t):
    assert(re.fullmatch('[Pp][0-9]', t))
    return 'p' + t[1]

  # pp for name as key
  def ppi_scopetree_name(self):
    l = [
      lambda tokens: "".join(map(self.ppi_thread_name, tokens)),
      lambda tokens: ":".join(tokens),
      lambda tokens: "::".join(tokens),
      lambda tokens: ":::".join(tokens),
      lambda tokens: "::::".join(tokens)
    ]
    p = self.get_st_parser(l)
    pr = p.parseString(self.scopetree)
    assert(len(pr) == 1)
    assert(type(pr[0]) is str)
    return pr[0]

  def ppi_incantations(self):
    return str(int(self.mem_stress)) + str(int(self.general_bc)) +\
      str(int(self.barrier)) + str(int(self.rand_threads))

  def ppi_num(self):
    assert(self.total == self.pos + self.neg)
    p = convert(self.pos)
    assert(type(p) == str)
    assert(not(self.pos > 0 and p == '0'))
    n = convert(self.total)
    s = p + '/' + n
    return s

  ########################
  # HTML pretty printers #
  ########################

  def pp_cell(self, i):
    i = ' ' * i
    s = i + '<td>' + self.pp_num() + '</td>\n'
    return s

  def pp_cell_link(self, i):
    i = ' ' * i
    s = i + '<td><a href="entries/' + self.get_id() + '.txt">' + self.pp_num() + '</a></td>\n' 
    return s

  def pp_cell_link_dir(self, i, diro='entries'):
    i = ' ' * i
    s = i + '<td><a href="' + diro + '/' + self.get_id() + '.txt">' + self.pp_num() + '</a></td>\n' 
    return s

  def pp_prefix(self, i):
    i = ' ' * i
    s = i + '<td>' + self.pp_scopetree() + '</td>\n' +\
        i + '<td>' + self.pp_memorymap() + '</td>\n' +\
        i + '<td>' + self.pp_name() + '</td>\n'
    return s

  def pp_name(self):
    na = self.name
    sn = self.short_name
    if sn:
      return sn
    return na

  def pp_num(self):
    return self.ppi_num()

  def pp_memorymap(self):
    return self.ppi_memorymap()

  def pp_thread(self, t):
    assert(re.fullmatch('[Pp][0-9]', t))
    return t[0] + '<sub>' + t[1] + '</sub>'

  def pp_scopetree(self):
    # Convert to other scopetree representation
    l = [
      lambda tokens: " ".join(map(self.pp_thread, tokens)),
      lambda tokens: " |<sub>warp</sub> ".join(tokens),
      lambda tokens: " |<sub>cta</sub> ".join(tokens),
      lambda tokens: " |<sub>ker</sub> ".join(tokens),
      lambda tokens: " |<sub>dev</sub> ".join(tokens)
    ]
    p = self.get_st_parser(l)
    pr = p.parseString(self.scopetree)
    assert(len(pr) == 1)
    assert(type(pr[0] == str))
    return pr[0]

  #########################
  # LaTeX pretty printers #
  #########################

  def ppl_cell(self):
    s = '& ' + self.pp_num()
    return s

  def ppl_thread(self, t):
    assert(re.fullmatch('[Pp][0-9]', t))
    return t[0] + '_{' + t[1] + '}'

  def ppl_scopetree(self):
    # Convert to other scopetree representation
    l = [
      lambda tokens: " ".join(map(self.pp_thread, tokens)),
      lambda tokens: " |_{warp} ".join(tokens),
      lambda tokens: " |_{cta} ".join(tokens),
      lambda tokens: " |_{ker} ".join(tokens),
      lambda tokens: " |_{dev} ".join(tokens)
    ]
    p = self.get_st_parser(l)
    pr = p.parseString(self.scopetree)
    assert(len(pr) == 1)
    assert(type(pr[0] == str))
    return pr[0]

# ------------------------------------------------------------------------------
# Full logs (collection of valid log entries)

# Regular log (incantations are implicit)
class Log:
  """Litmus log"""

  def __init__(self):
    self.d = collections.OrderedDict()
    # Filename of the log from which it was created (e.g. gtx660.txt)
    self.fn = ''

  ########
  # Base #
  ########

  def get(self, key):
    return self.d.get(key)

  def get_all(self):
    return list(self.d.values())

  def get_keys(self):
    return self.d.keys()

  # Check whether log contains any of the given keys
  def any_key(self, ks):
    assert(type(ks) == list)
    for k in ks:
      if self.d.get(k):
        return True
    return False

  def append(self, le):
    assert(type(le) == LogEntry)
    key = le.name
    assert(not(self.get(key)))
    self.d[key] = le

  def fix(self):
    d = collections.OrderedDict()
    for key, val in self.d.items():
      # Fix test name and name in raw log (raw_fixed)
      val.fix_name()
      assert(val.raw_fixed)
      key = self.get_key(val)
      d[key] = val
    self.d = d

  def sort(self):
    self.d = collections.OrderedDict(sorted(self.d.items()))

  # Verify key to entry mapping
  def verify(self):
    for key, val in self.d.items():
      assert(key == val.name)

  # Produce key from log entry
  def get_key(self, le):
    key = le.name
    assert(key)
    return key

  #######
  # I/O #
  #######

  ### Read log from string
  # s: string representing the whole log
  def from_string(self, s, fix_names, drop_dups, drop_numeric):
    assert(not self.d)
    assert(self.fn)

    if not s:
      return

    # Split log
    tag = 'GPU_PTX|RACE_OPENCL'
    header = r"([ \t]*%+[ \t]*\n" +\
      r"[ \t]*%+.+?%+[ \t]*\n" +\
      r"[ \t]*%+[ \t]*)"
    l = re.split('\n(' + tag + ')', s)
    # Reassemble
    if not l[0]:
      l = l[1:]
      assert(l[0] == tag)
    pre = []
    if l[0] != tag:
      if re.match(tag, l[0]):
        pre = [re.sub(header, "", l[0])]
      l = l[1:]
    n = len(l)
    chk(n % 2 == 0, ErrMsg.logform)
    rl = list()
    for i in range(0, n, 2):
      assert(re.fullmatch(tag, l[i]))
      el = re.sub(header, "", l[i+1])
      el = l[i] + el + '\n'
      rl.append(el)
    rl = pre + rl

    # Parse and enter into dict
    dups = 0
    numeric_dropped = 0
    failed_dropped = 0
    for es in rl:
      try:
        assert(25 < len(es) < 5000)
        le = LogEntry(es, self.fn)
      except FailureEntryError as e:
        failed_dropped += 1
        continue
      except InvalidEntryError as e:
        print(e)
        bail('invalid entry in litmus log')
      except NumericNameError as e:
        if drop_numeric:
          numeric_dropped += 1    
          continue
        else:
          bail('test with original numeric name: ' + str(e))

      if fix_names:
        le.fix_name()

      key = self.get_key(le)
      if key in self.d:
        if drop_dups:
          dups += 1
          continue
        else:
          bail('duplicate key: ' + key)
      self.d[key] = le

    # Statistics about parsing/log
    print('dropped ' + str(dups) + ' duplicate tests')
    print('dropped ' + str(numeric_dropped) + ' tests with numeric names')
    print('dropped ' + str(failed_dropped) + ' tests that failed')
    print('read ' + str(len(self.d)) + ' unique, successful tests')

  def from_file(self, fn, fix_names, drop_dups, drop_numeric):
    assert(not self.d)
    f = open(fn, 'r')
    s = f.read()
    f.close()
    self.fn = fn
    self.from_string(s, fix_names, drop_dups, drop_numeric)

  # Dump internal representation of log (for debugging purposes)
  def dump(self, f=sys.stdout):
    s = 'Log name: ' + self.fn + '\n'
    for key, val in self.d.items():
      s += 'Key: ' + key + '\n'
      s += val.dump() + '\n\n'
    if type(f) == str:
      f = open(f, 'w')
    f.write(s)
    f.close()

  # Dump raw log
  def dump_raw(self, f=sys.stdout):
    s = ''
    for key, val in self.d.items():
      assert(val.raw)
      s += val.raw
    if type(f) == str:
      f = open(f, 'w')
    f.write(s)
    f.close()

  # Dump raw log with fixed names
  def dump_raw_fixed(self, f=sys.stdout):
    s = ''
    for key, val in self.d.items():
      assert(val.raw_fixed)
      s += val.raw_fixed
    if type(f) == str:
      f = open(f, 'w')
    f.write(s)
    f.close()

# Log (explicit incantations)
class LogInc(Log):

  def get_key(self, le):
    key = le.name
    inc1 = str(le.general_bc)
    inc2 = str(le.mem_stress)
    inc3 = str(le.rand_threads)
    inc4 = str(le.barrier)
    assert(key)
    return '-'.join([key, inc1, inc2, inc3, inc4])

  # Get all unique short test names
  def get_names(self):
    short_names = [x.short_name for x in self.d.values()]
    return list(set(short_names))

  # Get all unique test names
  def get_long_names(self):
    long_names = [x.name for x in self.d.values()]
    return list(set(long_names))

  def verify(self):
    for key, val in self.d.items():
      mapped = self.get_key(val)
      assert(key == mapped)

