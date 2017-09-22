#!/usr/bin/env python3

import argparse
import sys
import copy
from functools import reduce, partial
import machinery as ma
from machinery import ErrMsg, chk, bail
from machinery import LogEntry as L
from generic import lty, tty, lins, tins, either_ty, ljcut, dupchk, listify

############
# Toplevel #
############

def mux(f, args):

  inc = args.incantations
  # Incantation log input is implicit for best
  if inc or f == best:
    args.lh = ma.LogInc
  else:
    args.lh = ma.Log

  inp = args.input
  l = list(listify(inp))
  if hasattr(args, 'output'):
    l.append(args.output)
  chk(not dupchk(l), 'duplicate files given')

  if f != normalize:
    # Get logs (normalize uses special options for this)
    c = type(inp) is list
    if not c:
      inp = [inp]
    inp = ma.get_logs(inp, lh=args.lh)
    if not c:
      inp = inp[0]
    args.input = inp

  f(args)

###############
# Subcommands #
###############

# Dump internal representation of log (for debugging)
def dump(args):
  log = args.input
  if args.internal:
    log.dump()
  elif args.raw:
    log.dump_raw()
  elif args.raw_fixed:
    log.dump_raw_fixed()

# Parse log file (if textual log) and perform some semantical checks
def parse(args):
  pass

# Pickle log object
def pickle(args):
  log = args.input
  assert(isinstance(log, ma.Log))
  out = args.output
  ma.gherkin(log, out)

# Fix names in log
def fix(args):
  log = args.input
  assert(isinstance(log, ma.Log))
  log.fix()
  out = args.output
  ma.gherkin(log, out)

# Sort log by name of litmus tests
def sort(args):
  log = args.input
  assert(isinstance(log, ma.Log))
  log.sort()
  out = args.output
  ma.gherkin(log, out)

# Produce sum of a list of logs (drop inconsistent entries)
def sum(args):
  logs = args.input
  assert(lins(logs, ma.Log))
  log = sum_hlp(logs, args.lh)
  out = args.output
  ma.gherkin(log, out)

# Merge two litmus logs (for duplicate entries, pick one and drop others)
def merge(args):
  logs = args.input
  assert(lins(logs, ma.Log))
  chk(len(logs) >= 2, 'need to provide at least two input files')

  ks = ma.get_keys(logs)
  merge_log = args.lh()
  merge_log.fn = args.new_name

  for k in ks:
    drop = False
    for log in logs:
      le = log.get(k)
      if le:
        if drop:
          print('dropping test ' + le.name + ' as seen previously')
          continue
        merge_log.append(le)
        drop = True

  out = args.output
  ma.gherkin(merge_log, out)

def drop(args):
  pass

def normalize(args):
  inp = args.input
  assert(type(inp) == str)
  # fix names, drop duplicates, drop tests with numeric names
  log = ma.get_logs(inp, args.lh, True, True, True)
  assert(lty(log, args.lh))
  log = log[0]
  out = args.output
  s = log.dump_raw_fixed(out)

def avg(args):
  logs = args.input
  assert(lins(logs, ma.Log))
  log = avg_hlp(logs, args.lh)
  out = args.output
  ma.gherkin(log, out)

# Compare two logs
def cmp(args):
  logs = args.input
  assert(lty(logs, ma.Log))
  assert(len(logs) == 2)
  log1 = logs[0]
  log2 = logs[1]
  a = args.all
  w = args.weaker
  stronger = args.stronger
  e = args.equal

  # Column sizes
  c1l = 60
  c2l = 20
  c3l = 20

  header = ljcut('Test', c1l) + ljcut(log1.fn, c2l) + ljcut(log2.fn, c3l) + '\n'
  s = header
  ks = ma.get_keys(logs)
  
  # Get formatted num
  def get_num(e, f):
    if e:
      return f(e)
    else:
      return '--'

  for k in ks:
    e1 = log1.get(k)
    e2 = log2.get(k)
    assert(e1 or e2)
    # All
    if a:
      s += ljcut(k, c1l)
      s += ljcut(get_num(e1, L.ppi_num), c2l)
      s += ljcut(get_num(e2, L.ppi_num), c3l)
      s += '\n'
      continue
    # Weaker
    if w and (e1 and e1.is_pos() and (not e2 or not e2.is_pos())):
      assert(e1.pos > 0)
      s += ljcut(k, c1l)
      s += ljcut(e1.ppi_num(), c2l)
      s += ljcut(get_num(e2, L.ppi_num), c3l)
      s += '\n'
      continue
    # Stronger
    if stronger and (e1 and not e1.is_pos() and (not e2 or e2.is_pos())):
      assert(e1.pos == 0)
      s += ljcut(k, c1l)
      s += ljcut(e1.ppi_num(), c2l)
      s += ljcut(get_num(e2, L.ppi_num), c3l)
      s += '\n'
      continue
    # Equal
    if e and (e1 and e2 and ((e1.is_pos() and e2.is_pos()) or (not e1.is_pos()
      and not e2.is_pos()))):
      s += ljcut(k, c1l)
      s += ljcut(e1.ppi_num(), c2l)
      s += ljcut(e2.ppi_num(), c3l)
      s += '\n'
      continue

  print(s)

# Assert a log relation
def assert_relation(args):

  logs = args.input
  assert(lty(logs, ma.Log))
  assert(len(logs) == 2)
  log1 = logs[0]
  log2 = logs[1]
  e = args.equal
  woe = args.weaker_or_equal
  soe = args.stronger_or_equal

  ks = ma.get_keys(logs)

  fail = False

  for k in ks:
    e1 = log1.get(k)
    e2 = log2.get(k)
    assert(e1 or e2)
    if (not e1) or (not e2):
      continue
    fail = False
    # Equal
    if e and (e1.is_pos() != e2.is_pos()):
      fail = True
      break
    # Weaker or equal
    if woe and (not e1.is_pos()) and e2.is_pos():
      fail = True
      break
    # Stronger or equal
    if soe and e1.is_pos() and (not e2.is_pos()):
      fail = True
      break
  
  if fail:
    print('fail')
    sys.exit(1)

  print('pass')

# Only keep best results from an incantation log
def best(args):
  log = args.input
  assert(type(log) == ma.LogInc)

  names = log.get_long_names()
  assert(lty(names, str))

  # Output log
  ol = ma.Log()
  ol.fn = log.fn

  entries = log.get_all()
  assert(lty(entries, L))
  for name in names:
    es = list(filter(lambda x: x.name == name, entries))
    assert(lty(entries, L))
    el = max(es, key=lambda x: x.pos)
    ol.append(el)

  out = args.output
  ma.gherkin(ol, out)

######################
# Subcommand helpers #
######################

# Produce one sum log from several individual logs
def sum_hlp(logs, lh):
  assert(lty(logs, lh))
  chk(len(logs) >= 2, 'need to provide at least two logs')

  ks = ma.get_keys(logs)
  sum_log = lh()
  sum_log.fn = 'sum'

  for k in ks:
    # Get base log entry for key
    ler = ma.get_entry(k, logs)
    sum_le = copy.deepcopy(ler)
    sum_le.raw = ''
    sum_le.raw_fixed = ''
    sum_le.pos = 0
    sum_le.neg = 0
    sum_le.total = 0
    sum_le.parent = 'sum'
    # Do consistency check and sum
    for log in logs:
      le = log.get(k)
      if le:
        try:
          ler.check_const(le)
        except ma.InconsistentTestsError as e:
          print(e)
          break
        sum_le.pos += le.pos
        sum_le.neg += le.neg
        assert(le.total == le.pos + le.neg)
        sum_le.total += le.total
    else:
      # Add entry to sum log
      sum_log.append(sum_le)

  return sum_log

# Produce one avg log from several individual logs
def avg_hlp(logs, lh):
  assert(lty(logs, lh))
  chk(len(logs) >= 2, 'need to provide at least two logs')

  ks = ma.get_keys(logs)
  avg_log = lh()
  avg_log.fn = 'avg'

  for k in ks:
    # Get base log entry for key
    ler = ma.get_entry(k, logs)
    avg_le = copy.deepcopy(ler)
    avg_le.raw = ''
    avg_le.raw_fixed = ''
    avg_le.pos = 0
    avg_le.neg = 0
    avg_le.parent = 'avg'
    # Do consistency check and sum
    for log in logs:
      le = log.get(k)
      if le:
        try:
          ler.check_const(le)
        except ma.InconsistentTestsError as e:
          print(e)
          break
        total = le.pos + le.neg
        avg_le.pos += le.pos / total
        avg_le.neg += le.neg / total
    else:
      # Add entry to sum log
      n = len(logs)
      avg_le.pos *= 100000
      avg_le.neg *= 100000
      avg_le.pos /= n
      avg_le.neg /= n
      avg_log.append(avg_le)

  return avg_log

#######################
# Command line parser #
#######################

# Open files and parse or unpickle (textual logs and pickles can be mixed)
class InputAction(argparse.Action):
  def __call__(self, parser, namespace, values, option_string=None):
    setattr(namespace, self.dest, values)

def many_to_one(p, h1='log (pickle)', h2='log (text or pickle)'):
  p.add_argument('output', help=h1)
  p.add_argument('input', nargs='+', action=InputAction, help=h2)

def one_to_one(p, h1='log (pickle)', h2='log (text or pickle)'):
  p.add_argument('output', help=h1)
  p.add_argument('input', action=InputAction, help=h2)

def get_cmdline_parser(cmds):
  p = argparse.ArgumentParser()

  # Dummy parent for common options
  parent = argparse.ArgumentParser(add_help=False)
  parent.add_argument('-i', '--incantations', action='store_true',
    help='input and output logs are incantation logs')

  sp = p.add_subparsers(help='use <subcommand> -h for further help', title=
    'subcommands')

  # dump: dump internal log representation
  p1 = sp.add_parser(cmds[0], parents=[parent], description='Dump the log')
  p1.add_argument('input', action=InputAction, help='log (text or pickle)')
  group = p1.add_mutually_exclusive_group(required=True)
  group.add_argument('-r', '--raw', action='store_true',
    help='dump raw source log')
  group.add_argument('-f', '--raw-fixed', action='store_true',
    help='dump fixed raw source log')
  group.add_argument('-n', '--internal', action='store_true',
    help='dump internal representation of log')
  p1.set_defaults(func=partial(mux, dump))

  # parse: format check
  p2 = sp.add_parser(cmds[1], parents=[parent],
    description='Parse log and perform some additional semantical checks.\
 Useful for checking whether the format of the log produced by e.g. litmus is\
 understood by this script.')
  p2.add_argument('input', action=InputAction,
    help='log (text or pickle)')
  p2.set_defaults(func=partial(mux, parse))

  # pickle: parse and pickle
  p3 = sp.add_parser(cmds[2], parents=[parent],
    description='Pickle the given log')
  one_to_one(p3)
  p3.set_defaults(func=partial(mux, pickle))

  # sort: sort log according to dict key
  p4 = sp.add_parser(cmds[3], parents=[parent],
    description='Sort the entries in the log according to their keys (~ sort\
 according to test names)')
  one_to_one(p4)
  p4.set_defaults(func=partial(mux, sort))

  # sum: sum logs
  p5 = sp.add_parser(cmds[4], parents=[parent])
  many_to_one(p5, h1='sum log (pickle)')
  p5.set_defaults(func=partial(mux, sum))

  # fix: -
  p6 = sp.add_parser(cmds[5], parents=[parent], description='Fix names in log\
 (deprecated)')
  one_to_one(p6)
  p6.set_defaults(func=partial(mux, fix))

  # merge: -
  s = """Merges several litmus logs. The internal name of the resulting log is
taken from the internal name of the first log. (deprecated)"""
  p7 = sp.add_parser(cmds[6], description=s, parents=[parent])
  p7.add_argument('output')
  p7.add_argument('new_name')
  p7.add_argument('input', nargs='+', action=InputAction)
  p7.set_defaults(func=partial(mux, merge))

  # drop: drop duplicates
  p8 = sp.add_parser(cmds[7], parents=[parent],
    description='Drop duplicates (deprecated)')
  one_to_one(p8)
  p8.set_defaults(func=partial(mux, drop))

  # normalize: normalize textual log
  p9 = sp.add_parser(cmds[8], parents=[parent],
    description='Attempt to fix test names in a log, by adding a scope tree and\
 a memory map designator. Example: SB+membar.ctas -> SB+membar.ctas-p0:p1-xgyg')
  p9.add_argument('output', help='log (text)')
  p9.add_argument('input', help='log (text)')
  p9.set_defaults(func=partial(mux, normalize))

  # avg: produce average log (cf. sum)
  p10 = sp.add_parser(cmds[9], parents=[parent])
  many_to_one(p10)
  p10.set_defaults(func=partial(mux, avg))

  # cmp: compare two logs
  p11 = sp.add_parser(cmds[10], parents=[parent],
    description='Compare two logs (e.g. a litmus and a herd log)')
  p11.add_argument('input', nargs=2, action=InputAction,
    help='log (text or pickle)')
  group = p11.add_mutually_exclusive_group(required=True)
  group.add_argument('-a', '--all', action='store_true',
    help='print all tests')
  group.add_argument('-s', '--stronger', action='store_true',
    help='print tests that were not observed in the first log, and observed or\
 not present in the second log')
  group.add_argument('-w', '--weaker', action='store_true',
    help='print tests that were observed in the first log, and not observed or\
 not present in the second log')
  group.add_argument('-e', '--equal', action='store_true',
    help='print tests that yielded the same result in both logs')
  p11.set_defaults(func=partial(mux, cmp))

  # assert: assert log relation
  p12 = sp.add_parser(cmds[11], parents=[parent],
    description='Assert log relation (e.g. between a litmus and a herd log)')
  p12.add_argument('input', nargs=2, action=InputAction,
    help='log (text or pickle)')
  group = p12.add_mutually_exclusive_group(required=True)
  group.add_argument('-e', '--equal', action='store_true',
    help='assert equality (for all tests that exist in both logs)')
  group.add_argument('-s', '--stronger-or-equal', action='store_true',
    help='assert that the first log is stronger or the same as the second log\
 (only considering tests that exist in both logs)')
  group.add_argument('-w', '--weaker-or-equal', action='store_true',
    help='assert that the first log is weaker or the same as the second log\
 (only considering tests that exist in both logs)')
  p12.set_defaults(func=partial(mux, assert_relation))

  # best: only keep best results from an incantation log
  p13 = sp.add_parser(cmds[12], parents=[parent],
    description='Keep best results from an incantation log')
  p13.add_argument('output', help='log (pickle)')
  p13.add_argument('input', help='incantation log (text or pickle)')
  p13.set_defaults(func=partial(mux, best))

  return p

if __name__ == "__main__":
  if len(sys.argv) == 1:
    sys.argv += ['-h']
  cmd = sys.argv[1]
  ma.setup_err_handling('log2log.py')
  cmds = ['dump', 'parse', 'pickle', 'sort', 'sum', 'fix', 'merge', 'drop',
    'normalize', 'avg', 'cmp', 'assert', 'best']
  p = get_cmdline_parser(cmds)
  if cmd not in cmds:
    p.print_help()
    sys.exit(2)
  print('cmd: ' + cmd)
  pr = p.parse_args()
  pr.func(pr)

