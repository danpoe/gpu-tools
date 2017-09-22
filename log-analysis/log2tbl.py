#!/usr/bin/env python3

import argparse
import os
import sys
import collections
import textwrap
from functools import partial
import machinery as ma
from machinery import ErrMsg, chk, bail
from machinery import LogEntry as L
from generic import lty, interleave, itemify, dupchk, listify, w_str

# ------------------------------------------------------------------------------

# Html file (including navigation and sections)
class HtmlFile:
  """Html file representing litmus test results"""

  sp = '  '

  # HTML prefix before tables
  prefix = textwrap.dedent("""\
  <!DOCTYPE html>
  <html>
  <head>
  <meta charset="UTF-8">
  <title>GPU Litmus Test Results</title>
  <link rel="stylesheet" href="common.css" type="text/css" media="screen"/>
  </head>

  <body>
  <div class="outer">
  <div class="inner">

  <h1>GPU Litmus Test Results</h1>
  <br>

  <center>
  To view the logfile for a test and chip, click on the corresponding number.
  The logfile contains the litmus test code, and the incantations used for the
  test run.
  </center>
  <br><br>

  """)

  # HTML suffix after tables
  suffix = textwrap.dedent("""
  </div>
  </div>
  </body>
  </html>
  """)

  def __init__(self):
    self.items = []
    self.nav = '<h4>Contents</h4>\n'
    self.secn = 0
    self.last_level = -1

  def add_nav_item(self, link, level):
    sp = self.sp
    li = sp * (level + 1)
    ul = sp * (self.last_level + 1)
    if level == self.last_level:
      self.nav += li + '<li><a href="#id' + str(self.secn) + '">' + link +\
        '</a></li>\n'
    elif level == self.last_level + 1:
      self.nav += ul + '<ul>\n'
      self.nav += li + '<li><a href="#id' + str(self.secn) + '">' + link +\
        '</a></li>\n'
    elif level < self.last_level:
      self.close_nav(level)
      self.nav += li + '<li><a href="#id' + str(self.secn) + '">' + link +\
        '</a></li>\n'
    else:
      assert(False)
    self.last_level = level

  def close_nav(self, level):
    sp = self.sp
    while self.last_level > level:
      self.nav += sp * self.last_level + '</ul>\n'
      self.last_level -= 1

  def new_section(self, heading, level):
    assert(0 <= level <= 2)
    l = str(level+2)
    s = '<h' + l + '><a id="id' + str(self.secn) + '">' + heading + '</a></h'\
      + l + '>\n'
    self.items.append(s)
    self.add_nav_item(heading, level)
    self.secn += 1

  def add_html(self, html):
    self.items.append(html)

  def finish(self, nav=True):
    self.close_nav(-1)
    l = [self.prefix]
    if nav:
      l += [self.nav]
    l += self.items + [self.suffix]
    self.s = ''.join(l)

  def write(self, fn):
    assert(self.s)
    f = open(fn, 'w')
    f.write(self.s)
    f.close()

# ------------------------------------------------------------------------------

### Used by all HTML file producers
# ks: list of test names to include in the table
# logs: list of log objects (only logs which have the key are included in the
#       table)
def produce_table(ks, logs, diro='entries'):
  logs = [ l for l in logs if l.any_key(ks) ]  
  s = '<table>\n'

  # Process header
  s += '<tr>\n'
  s += '  <th>Scope tree</th>\n'
  s += '  <th>Memory map</th>\n'
  s += '  <th>Name</th>\n'
  for log in logs:
    # Remove directory prefix and suffix
    name = os.path.basename(log.fn)
    idx = name.find('.')
    if idx != -1:
      name = name[:idx]
    s += '  <th>' + name + '</th>\n'
  s += '</tr>\n'

  # Process rows
  for k in ks:
    # Start new row
    s += '<tr>\n'
    le = ma.get_entry(k, logs)
    s += le.pp_prefix(2)
    for log in logs:
      e = log.get(k)
      if e:
        s += e.pp_cell_link_dir(2, diro)
        # Produce file containing raw litmus log
        e.store_log_dir(diro)
      else:
        s += '<td><a href="">---</a></td>\n'
    s += '</tr>\n'

  s += '</table>\n'
  return s

# Filtering according to scopes and memory regions; no filtering according to
# names
def get_section_filters():
  def c(f, g):
    return lambda e: f(e) and g(e)
  # List of functions that each take a log entry
  d = [
    # Simple scopes, global memory
    c(L.is_warp, L.is_global),
    c(L.is_cta, L.is_global),
    c(L.is_ker, L.is_global),
    # Simple scopes, shared memory
    c(L.is_warp, L.is_shared),
    # Simple scopes, mixed memory
    c(L.is_warp, L.is_mixed_mem),
    # Mixed scopes, global memory
    c(L.is_mixed_scope, L.is_global),
    # Mixed scopes, shared memory
    c(L.is_mixed_scope, L.is_shared),
    # Mixed scopes, mixed memory
    c(L.is_mixed_scope, L.is_mixed_mem)
  ]
  return d

def get_section_names():
  # Parallel the above functions
  names = [
    'Different warps, same CTA; global memory',
    'Different CTAs, same kernel; global memory',
    'Different kernels, same device; global memory',
    'Different warps, same CTA; shared memory',
    'Different warps, same CTA; mixed memory',
    'Mixed scopes, global memory',
    'Mixed scopes, shared memory',
    'Mixed scopes, mixed memory'
  ]
  return names

# Get key patterns per axiom
def get_axiom_patterns():
  l = [
    ('SC per location', ['CO', 'Co']),
    ('No Thin Air', ['(LB$)|(LB\+)|(LB\-)']),
    ('Observation', ['(MP$)|(MP\+)|(MP\-)', 'WRC', 'ISA2']),
    ('Propagation Light', ['2\+2W', 'W\+RW\+2W', '(S$)|(S\+)|(S\-)']),
    ('Propagation Heavy', [ 'SB', '(R$)|(R\+)|(R\-)', 'RWC', 'IRIW' ])
  ]
  return l

# ------------------------------------------------------------------------------

############
# Toplevel #
############

# f: function to be called; args: arguments to the function
def mux(f, args):

  inp = args.input
  l = list(listify(inp))
  if hasattr(args, 'out'):
    l.append(args.out)
  chk(not dupchk(l), 'duplicate files given')

  # Read ordinary logs (if we do not want to read an incantation log)
  if f != incantations and f != incantations_flat and f != incantations_html_flat:
    c = type(inp) is list
    if not c:
      inp = [inp]
    inp = ma.get_logs(inp, lh=ma.Log)
    if not c:
      inp = inp[0]
    args.input = inp

  f(args)

###############
# Subcommands #
###############

### Produce table with sections according to axioms
def classified(args):
  pos = args.pos
  logs = args.input
  assert(lty(logs, ma.Log))
  assert(hasattr(args, 'diro'))

  l = get_axiom_patterns()

  h = HtmlFile()
  all_matching = []
 
  for name, val in l:
    ks = ma.get_matching_keys(val, logs)
    if pos:
      ks = ma.get_pos_keys(logs, ks)
    all_matching += ks
    if ks:
      h.new_section(name, 0)
      s = produce_table(ks, logs, diro=args.diro)
      h.add_html(s)

  all_matching = set(all_matching)
  if pos:
    ks = ma.get_pos_keys(logs)
  else:
    ks = ma.get_keys(logs)
  ks = set(ks) - all_matching
  ks = list(ks)

  if ks:
    h.new_section('Other', 0)
    ks.sort()
    s = produce_table(ks, logs)
    h.add_html(s)

  h.finish()
  h.write(args.out)

### Two level classification
def two_level(args):
  pos = args.pos
  logs = args.input
  assert(lty(logs, ma.Log))
  assert(hasattr(args, 'diro'))

  l = get_axiom_patterns()

  h = HtmlFile()
  all_matching = []

  for name, val in l:
    ks_s = ma.get_matching_keys(val, logs)
    if pos:
      ks_s = ma.get_pos_keys(logs, ks_s)
    all_matching += ks_s
    if ks_s:
      h.new_section(name, 0)
      # Now divide by other sections
      filters = get_section_filters()
      names = get_section_names()
      for f, name in zip(filters, names):
        ks = ma.get_filtered_keys(f, logs, ks_s)
        if pos:
          ks = ma.get_pos_keys(logs, ks)
        if ks:
          h.new_section(name, 1)
          s = produce_table(ks, logs, diro=args.diro)
          h.add_html(s)

  # Rest
  all_matching = set(all_matching)
  if pos:
    ks_s = ma.get_pos_keys(logs)
  else:
    ks_s = ma.get_keys(logs)
  ks_s = set(ks_s) - all_matching
  ks_s = list(ks_s)

  if ks_s:
    h.new_section('Other', 0)
    ks_s.sort()

    filters = get_section_filters()
    names = get_section_names()
    for f, name in zip(filters, names):
      ks = ma.get_filtered_keys(f, logs, ks_s)
      if pos:
        ks = ma.get_pos_keys(logs, ks)
      if ks:
        h.new_section(name, 1)
        s = produce_table(ks, logs, diro=args.diro)
        h.add_html(s)

  h.finish()
  h.write(args.out)

### Produce table with sections according to scopes and memory regions
def sections(args):
  pos = args.pos
  logs = args.input
  assert(lty(logs, ma.Log))
  assert(hasattr(args, 'diro'))

  s = ''
  h = HtmlFile()

  filters = get_section_filters()
  names = get_section_names()
  for f, name in zip(filters, names):
    ks = ma.get_filtered_keys(f, logs)
    if pos:
      ks = ma.get_pos_keys(logs, ks)
    if ks:
      h.new_section(name, 0)
      s = produce_table(ks, logs, diro=args.diro)
      h.add_html(s)

  h.finish()
  h.write(args.out)

### Produce flat table with all tests
def flat(args):
  pos = args.pos
  logs = args.input
  assert(lty(logs, ma.Log))
  assert(hasattr(args, 'diro'))

  # Get all the keys
  if pos:
    ks = ma.get_pos_keys(logs)
  else:
    ks = ma.get_keys(logs)
  s = produce_table(ks, logs, diro=args.diro)

  h = HtmlFile()
  h.add_html(s)
  h.finish(nav=False)
  h.write(args.out)

# ------------------------------------------------------------------------------

### Fill up table line by line
# l: list of items
# sep: separator
# end: end of line
# n: number of elements on line
def fill_up(l, sep, end, nl):
  n = len(l)
  s = ""
  while l:
    chunk = l[:nl]
    line = sep.join(chunk)
    s += line + ((nl - len(chunk)) * sep) + end  
    l = l[nl:]
  return s

def latex_tbl(f, logs, n):
  ks = ma.get_filtered_keys(f, logs)
  sep = ' & '
  s = ''
  def mapper(k):
    e = ma.get_entry(k, logs)
    return e.short_name.lower() + sep + str(e.pos) 
  l = list(map(mapper, ks))
  header = sep.join(["Test" + sep + "Freq."] * n) + "\\\\\n"
  header += '\midrule\n'
  s = header + fill_up(l, sep, '\\\\\n', n)
  s += '\\bottomrule\n'
  return s

def latex_tbl2(f, logs, n):
  ks = ma.get_filtered_keys(f, logs)
  sep = ' & '
  s = '\midrule\n'
  def mapper(k):
    e = ma.get_entry(k, logs)
    return e.short_name.lower(), str(e.pos)
  l = list(map(mapper, ks))
  l1, l2 = zip(*l)
  l = interleave(l1, l2, n)
  s = fill_up(l, sep, '\\\\\n', n)
  s += '\\bottomrule\n'
  return s

### Produce latex tables
def latex(args):
  pos = args.pos
  logs = args.input
  assert(type(logs) == ma.Log)
  
  n = 4

  l = ['CO', 'Co', 'LB[^+]', 'MP[^+]', 'WRC[^+]', 'ISA2[^+]', '2\+2W[^+]',
       'W\+RW\+2W[^+]', 'S[^+]+$', 'SB[^+]', 'R[^+]+$', 'RWC[^+]', 'IRIW[^+]']

  # Produce d-warp:s-cta table, global memory
  f = lambda e: L.is_global(e) and \
                ((L.is_warp(e) and L.does_match(e, l)) or
                 (L.does_match(e, ['CoWW', 'COWW'])))
  s = latex_tbl(f, logs, n)

  s += '\n'
  
  # Produce d-warp:s-cta table, shared memory
  f = lambda e: L.is_shared(e) and \
                ((L.is_warp(e) and L.does_match(e, l)) or
                 (L.does_match(e, ['CoWW', 'COWW'])))
  s += latex_tbl(f, logs, n)

  s += '\n'

  # Produce d-cta:s-ker table, global memory
  f = lambda e: L.is_global(e) and \
                ((L.is_cta(e) and L.does_match(e, l))) 
  s += latex_tbl(f, logs, n)

  w_str(args.out, s)

def latex2(args):
  pos = args.pos
  logs = args.input
  assert(type(logs) == ma.Log)

  sep = ' & '
  l = ['CO', 'Co', 'LB[^+]', 'MP[^+]', 'WRC[^+]', 'ISA2[^+]', '2\+2W[^+]',
       'W\+RW\+2W[^+]', 'S[^+]+$', 'SB[^+]', 'R[^+]+$', 'RWC[^+]', 'IRIW[^+]']
  lc = ['CoWW', 'COWW']

  ks = ma.get_matching_keys(l, logs)
  
  # Names + s1 + global memory
  f = lambda e: L.is_global(e) and (L.is_warp(e) or L.does_match(e, lc))
  ks1 = ma.get_filtered_keys(f, logs, ks)
  ks1.sort()
  n = len(ks1)
  l = list()
  for i, k in enumerate(ks1):
    e = ma.get_entry(k, logs)
    l.append(e.short_name.lower() + sep + str(e.pos) + sep)

  # s1 + shared memory
  f = lambda e: L.is_shared(e) and (L.is_warp(e) or L.does_match(e, lc))
  ks2 = ma.get_filtered_keys(f, logs, ks)
  ks2.sort()
  assert(len(ks2) == n)
  for i, k in enumerate(ks2):
    e = ma.get_entry(k, logs)
    l[i] += str(e.pos) + sep

  # s2 + global memory  
  f = lambda e: L.is_global(e) and (L.is_cta(e) or L.does_match(e, lc))
  ks3 = ma.get_filtered_keys(f, logs, ks)
  ks3.sort()
  assert(len(ks3) == n)
  for i, k in enumerate(ks3):
    e = ma.get_entry(k, logs)
    l[i] += str(e.pos) + '\\\\'

  s = '\n'.join(l)
  w_str(args.out, s)

### Produce latex tables
def latex3(args):
  pos = args.pos
  logs = args.input
  assert(type(logs) == ma.Log)
  
  n = 8

  l = ['CO', 'Co', 'LB[^+]', 'MP[^+]', 'WRC[^+]', 'ISA2[^+]', '2\+2W[^+]',
       'W\+RW\+2W[^+]', 'S[^+]+$', 'SB[^+]', 'R[^+]+$', 'RWC[^+]', 'IRIW[^+]']

  # Produce d-warp:s-cta table, global memory
  f = lambda e: L.is_global(e) and \
                ((L.is_warp(e) and L.does_match(e, l)) or
                 (L.does_match(e, ['CoWW', 'COWW'])))
  s = latex_tbl2(f, logs, n)

  s += '\n'
  
  # Produce d-warp:s-cta table, shared memory
  f = lambda e: L.is_shared(e) and \
                ((L.is_warp(e) and L.does_match(e, l)) or
                 (L.does_match(e, ['CoWW', 'COWW'])))
  s += latex_tbl2(f, logs, n)

  s += '\n'

  # Produce d-cta:s-ker table, global memory
  f = lambda e: L.is_global(e) and \
                ((L.is_cta(e) and L.does_match(e, l))) 
  s += latex_tbl2(f, logs, n)

  w_str(args.out, s)

# ------------------------------------------------------------------------------

### Produce incantations tables
# All tests that are not explicitely listed under 'line filters' in this file
# are ignored; non-existing tests and non-existing entries (e.g. for a certain
# combination of incantations) are also ignored
def incantations(args):
  log = args.input
  assert(type(log) == str)

  # Get chip name
  chip = os.path.basename(log)
  assert(type(chip) == str)
  chip_old = chip
  while True:
    chip = os.path.splitext(chip)[0]
    if chip == chip_old:
      break
    chip_old = chip  
  assert(type(chip) == str)

  # Get incantation log
  log = ma.get_logs(log, lh=ma.LogInc)
  assert(lty(log, ma.LogInc))
  assert(len(log) == 1)
  log = log[0]

  out_base = args.out
  assert(out_base)

  les = log.get_all()
  assert(lty(les, L))

  # Table header
  prefix = textwrap.dedent(r"""
  \definecolor{Gray}{gray}{0.85}
  \newcolumntype{g}{>{\columncolor{Gray}}r}
  \newcolumntype{h}{>{\columncolor{Gray}}c}

  \begin{tabular}{l g g g g r r r r g g g g r r r r}
  \toprule
  \multicolumn{17}{l}{Chip: <chip>}\\
  \multicolumn{17}{l}{GPU Configuration: <config>}\\
  \hline
  & \multicolumn{4}{h}{Critical Incantations:} & \multicolumn{4}{c}{Critical Incantations:} & \multicolumn{4}{h}{Critical Incantations:} & \multicolumn{4}{c}{Critical Incantations:}\\
  & \multicolumn{4}{h}{none} & \multicolumn{4}{c}{GBC} & \multicolumn{4}{h}{MS} & \multicolumn{4}{c}{GBC+MS}\\
  & \multicolumn{4}{h}{Extra Incantations:} & \multicolumn{4}{c}{Extra Incantations:} & \multicolumn{4}{h}{Extra Incantations:} & \multicolumn{4}{c}{Extra Incantations:}\\
  & none & R & S & R+S & none & R & S & R+S & none & R & S & R+S & none & R & S & R+S\\
  \hline
  """)

  # Scope and mem filters, including table description and filename suffix
  sfs = [
    (lambda e: L.is_warp(e) and L.is_global(e),
     'All threads in different warps, global memory',
     's1-global'),
    (lambda e: L.is_warp(e) and L.is_shared(e),
     'All threads in different warps, shared memory',
     's1-shared'),
    (lambda e: L.is_cta(e) and L.is_global(e),
     'All threads in different CTAs, global memory',
     's2-global')
  ]

  # Column filters
  fs1 = [lambda e: not L.is_mem_stress(e), lambda e: L.is_mem_stress(e)]
  fs2 = [lambda e: not L.is_general_bc(e), lambda e: L.is_general_bc(e)]
  fs3 = [lambda e: not L.is_barrier(e), lambda e: L.is_barrier(e)]
  fs4 = [lambda e: not L.is_rand_threads(e), lambda e: L.is_rand_threads(e)]
  nc = 16

  # Line filters
  lfs = [
    ('uniproc', ['corr', 'corw', 'cowr', 'coww']),
    ('observation', ['mp', 'isa2', 'wrc']),
    ('prop light', ['2+2w', 'w+rw+2w', 's']),
    ('prop heavy', ['sb', 'rwc', 'iriw', 'r']),
    ('thin air', ['lb'])
  ]
  lfs = collections.OrderedDict(lfs)

  for sf, cfg, suf in sfs:
    s = prefix
    s = s.replace('<config>', cfg, 1)
    s = s.replace('<chip>', chip, 1)
    l1 = list(filter(sf, les))
    assert(lty(l1, L))
    for sec, tests in lfs.items():
      tests.sort()
      # Section header
      s += r'{\bf ' + sec + '}' + (' &' * nc) + r'\\' + '\n'
      for t in tests:
        # Get all tests that match a simple test name (like rwc)
        l2 = list(filter(partial(L.simple_match, s=t), l1))
        assert(lty(l2, L))
        if (len(l2) == 0):
          continue
        s += t
        for i in range(0, nc):
          i1 = (i & 0b1000) >> 3
          i2 = (i & 0b0100) >> 2
          i3 = (i & 0b0010) >> 1
          i4 = (i & 0b0001)
          f1 = fs1[i1]
          f2 = fs2[i2]
          f3 = fs3[i3]
          f4 = fs4[i4]
          f = lambda e: f1(e) and f2(e) and f3(e) and f4(e)
          entry = '-'
          item = list(filter(f, l2))
          if item:
            item = itemify(item)
            assert(type(item) == L)
            entry = item.pos
          # ppi_incantations: mem_stress, general_bc, barrier, rand_threads
          s += ' & ' + str(entry)
        s += '\\\\\n'
      s += '\\hline\n'
    s += '\\end{tabular}\n'
    # Write table to file
    f_out = out_base + '-' + suf + '.tex'
    w_str(f_out, s)

# ------------------------------------------------------------------------------

### Produce flat incantation tables
def incantations_flat(args):
  log = args.input
  assert(type(log) == str)

  
  chip = os.path.basename(log)
  assert(type(chip) == str)
  chip_old = chip
  while True:
    chip = os.path.splitext(chip)[0]
    if chip == chip_old:
      break
    chip_old = chip  
  assert(type(chip) == str)

  log = ma.get_logs(log, lh=ma.LogInc)
  assert(lty(log, ma.LogInc))
  assert(len(log) == 1)
  log = log[0]

  # Prefix of output filename, default is the command name
  out_base = args.out
  assert(out_base)

  les = log.get_all()
  assert(lty(les, L))

  short_names = log.get_names()
  assert(lty(short_names, str))
  short_names.sort()

  # Table header
  prefix = textwrap.dedent(r"""
  \definecolor{Gray}{gray}{0.85}
  \newcolumntype{g}{>{\columncolor{Gray}}r}
  \newcolumntype{h}{>{\columncolor{Gray}}c}

  \begin{tabular}{l g g g g r r r r g g g g r r r r}
  \toprule
  \multicolumn{17}{l}{Chip: <chip>}\\
  \multicolumn{17}{l}{GPU Configuration: <config>}\\
  \hline
  & \multicolumn{4}{h}{Critical Incantations:} & \multicolumn{4}{c}{Critical Incantations:} & \multicolumn{4}{h}{Critical Incantations:} & \multicolumn{4}{c}{Critical Incantations:}\\
  & \multicolumn{4}{h}{none} & \multicolumn{4}{c}{GBC} & \multicolumn{4}{h}{MS} & \multicolumn{4}{c}{GBC+MS}\\
  & \multicolumn{4}{h}{Extra Incantations:} & \multicolumn{4}{c}{Extra Incantations:} & \multicolumn{4}{h}{Extra Incantations:} & \multicolumn{4}{c}{Extra Incantations:}\\
  & none & R & S & R+S & none & R & S & R+S & none & R & S & R+S & none & R & S & R+S\\
  \hline
  """)

  # Scope and mem filters, including table description and filename suffix
  sfs = [
    (lambda e: L.is_warp(e) and L.is_global(e),
     'All threads in different warps, global memory',
     's1-global'),
    (lambda e: L.is_warp(e) and L.is_shared(e),
     'All threads in different warps, shared memory',
     's1-shared'),
    (lambda e: L.is_cta(e) and L.is_global(e),
     'All threads in different CTAs, global memory',
     's2-global')
  ]

  # Column filter building blocks (need to be combined to yield a single column
  # filter)
  fs1 = [lambda e: not L.is_mem_stress(e), lambda e: L.is_mem_stress(e)]
  fs2 = [lambda e: not L.is_general_bc(e), lambda e: L.is_general_bc(e)]
  fs3 = [lambda e: not L.is_barrier(e), lambda e: L.is_barrier(e)]
  fs4 = [lambda e: not L.is_rand_threads(e), lambda e: L.is_rand_threads(e)]
  nc = 16

  # Scope and mem filters, table description, filename suffix
  for sf, cfg, suf in sfs:
    s = prefix
    s = s.replace('<config>', cfg, 1)
    s = s.replace('<chip>', chip, 1)
    l1 = list(filter(sf, les))
    assert(lty(l1, L))
    for t in short_names:
      l2 = list(filter(partial(L.simple_match, s=t), l1))
      assert(lty(l2, L))
      if (len(l2) == 0):
        continue
      # Name of test
      s += t
      for i in range(0, nc):
        i1 = (i & 0b1000) >> 3
        i2 = (i & 0b0100) >> 2
        i3 = (i & 0b0010) >> 1
        i4 = (i & 0b0001)
        f1 = fs1[i1]
        f2 = fs2[i2]
        f3 = fs3[i3]
        f4 = fs4[i4]
        f = lambda e: f1(e) and f2(e) and f3(e) and f4(e)
        entry = '-'
        item = list(filter(f, l2))
        if item:
          item = itemify(item)
          assert(type(item) == L)
          entry = item.pos
        # ppi_incantations: mem_stress, general_bc, barrier, rand_threads
        s += ' & ' + str(entry)
      s += '\\\\\n'

    s += '\\end{tabular}\n'
    # Write table to file
    f_out = out_base + '-' + suf + '.tex'
    w_str(f_out, s)

# ------------------------------------------------------------------------------

### Produce flat incantation tables
def incantations_html_flat(args):
  log = args.input
  assert(type(log) == str)
  assert(hasattr(args, 'diro'))

  chip = os.path.basename(log)
  assert(type(chip) == str)
  chip_old = chip
  while True:
    chip = os.path.splitext(chip)[0]
    if chip == chip_old:
      break
    chip_old = chip  
  assert(type(chip) == str)

  log = ma.get_logs(log, lh=ma.LogInc)
  assert(lty(log, ma.LogInc))
  assert(len(log) == 1)
  log = log[0]

  # Prefix of output filename, default is the command name
  out_base = args.out
  assert(out_base)

  les = log.get_all()
  assert(lty(les, L))

  short_names = log.get_names()
  assert(lty(short_names, str))
  short_names.sort()

  # Table header
  # '&nbsp;': non-breaking space
  # '&#x2713;': checkmark
  prefix = textwrap.dedent(r"""
  <!DOCTYPE html>
  <html style="background:white;">
  <head>
  <meta charset="UTF-8">
  <title>Evaluating incantations</title>
  <link rel="stylesheet" href="common.css" type="text/css" media="screen"/>
  <style>

  ul {
    padding-top: 10px;
  }

  li {
    padding-top: 5px;
  }

  th, td {
    text-align: right;
    padding: 5px;
    padding-right: 15px;
    padding-left: 15px;
  }

  td:nth-child(1) {
    text-align: left;
  }

  tr:nth-child(1), tr:nth-child(5) {
    border-bottom: 2px solid black;
  }

  table {
    border-top: none;
  }

  </style>
  </head>

  <body>
  <div class="outer" style="width: 100%;">
  <div class="inner">
  <h1>Evaluating incantations</h1>

  <br>

  <center>
  To view the logfile for a test, click on the corresponding number. The logfile
  also contains the litmus test code. When a dash appears instead of a result,
  it is either because optcheck failed or because there were insufficient
  resources on the chip to run the test.
  </center>

  <br>

  <center>
  <table style="border:none">
  <tr style="border:none">
    <td style="text-align:left">Chip:</td>
    <td style="text-align:left"> <chip> </td>
  </tr>
  <tr style="border:none">
    <td style="text-align:left">Config:</td>
    <td style="text-align:left"> <config> </td>
  </tr>
  </table>
  </center>

  <br>

  <table>
  <tr>
    <td> </td>
    <td>1</td>
    <td>2</td>
    <td>3</td>
    <td>4</td>
    <td>5</td>
    <td>6</td>
    <td>7</td>
    <td>8</td>
    <td>9</td>
    <td>10</td>
    <td>11</td>
    <td>12</td>
    <td>13</td>
    <td>14</td>
    <td>15</td>
    <td>16</td>
  </tr>
  <tr>
    <td>memory&nbsp;stress</td>
    <td>      </td><td>      </td><td>      </td><td>      </td>
    <td>      </td><td>      </td><td>      </td><td>      </td>
    <td>&#x2713;</td><td>&#x2713;</td><td>&#x2713;</td><td>&#x2713;</td>
    <td>&#x2713;</td><td>&#x2713;</td><td>&#x2713;</td><td>&#x2713;</td>
  </tr>
  <tr>
    <td>general&nbsp;bank&nbsp;conflicts</td>
    <td>      </td><td>      </td><td>      </td><td>      </td>
    <td>&#x2713;</td><td>&#x2713;</td><td>&#x2713;</td><td>&#x2713;</td>
    <td>      </td><td>      </td><td>      </td><td>      </td>
    <td>&#x2713;</td><td>&#x2713;</td><td>&#x2713;</td><td>&#x2713;</td>
  </tr>
  <tr>
    <td>thread&nbsp;synchronisation</td>
    <td>      </td><td>      </td><td>&#x2713;</td><td>&#x2713;</td>
    <td>      </td><td>      </td><td>&#x2713;</td><td>&#x2713;</td>
    <td>      </td><td>      </td><td>&#x2713;</td><td>&#x2713;</td>
    <td>      </td><td>      </td><td>&#x2713;</td><td>&#x2713;</td>
  </tr>
  <tr>
    <td>thread&nbsp;randomisation</td>
    <td>      </td><td>&#x2713;</td><td>      </td><td>&#x2713;</td>
    <td>      </td><td>&#x2713;</td><td>      </td><td>&#x2713;</td>
    <td>      </td><td>&#x2713;</td><td>      </td><td>&#x2713;</td>
    <td>      </td><td>&#x2713;</td><td>      </td><td>&#x2713;</td>
  </tr>
  """)

  # Scope and mem filters, including table description and filename suffix
  sfs = [
    (lambda e: L.is_warp(e) and L.is_global(e),
     'All threads in different warps, global memory',
     's1-global'),
    (lambda e: L.is_warp(e) and L.is_shared(e),
     'All threads in different warps, shared memory',
     's1-shared'),
    (lambda e: L.is_cta(e) and L.is_global(e),
     'All threads in different CTAs, global memory',
     's2-global')
  ]

  # Column filter building blocks (need to be combined to yield a single column
  # filter)
  fs1 = [lambda e: not L.is_mem_stress(e), lambda e: L.is_mem_stress(e)]
  fs2 = [lambda e: not L.is_general_bc(e), lambda e: L.is_general_bc(e)]
  fs3 = [lambda e: not L.is_barrier(e), lambda e: L.is_barrier(e)]
  fs4 = [lambda e: not L.is_rand_threads(e), lambda e: L.is_rand_threads(e)]
  nc = 16

  # Scope and mem filters, table description, filename suffix
  for sf, cfg, suf in sfs:
    s = prefix
    s = s.replace('<config>', cfg, 1)
    s = s.replace('<chip>', chip, 1)
    l1 = list(filter(sf, les))
    assert(lty(l1, L))
    for t in short_names:
      l2 = list(filter(partial(L.simple_match, s=t), l1))
      assert(lty(l2, L))
      if (len(l2) == 0):
        continue
      # Name of test
      s += '<tr>\n'
      s += '<td>' + t + '</td>'
      for i in range(0, nc):
        i1 = (i & 0b1000) >> 3
        i2 = (i & 0b0100) >> 2
        i3 = (i & 0b0010) >> 1
        i4 = (i & 0b0001)
        f1 = fs1[i1]
        f2 = fs2[i2]
        f3 = fs3[i3]
        f4 = fs4[i4]
        f = lambda e: f1(e) and f2(e) and f3(e) and f4(e)
        entry = '-'
        item = list(filter(f, l2))
        if item:
          item = itemify(item)
          assert(type(item) == L)
          entry = item.pos
          s += item.pp_cell_link_dir(2, args.diro)
          # Produce file containing raw litmus log
          item.store_log_dir(args.diro)
        else:
          # ppi_incantations: mem_stress, general_bc, barrier, rand_threads
          s += '<td>' + str(entry) + '</td>'
      s += '</tr>\n'

    s += """
    </table>
    </div>
    </div>
    </body>
    </html>
    """

    # Write table to file
    f_out = out_base + '-' + suf + '.html'
    w_str(f_out, s)

# ------------------------------------------------------------------------------

#######################
# Command line parser #
#######################

# Open files and parse or unpickle
class InputAction(argparse.Action):
  def __call__(self, parser, namespace, values, option_string=None):
    setattr(namespace, self.dest, values)

def get_cmdline_parser(cmds):
  # Parent of all
  p = argparse.ArgumentParser()
  
  # Dummy parent for common options
  parent = argparse.ArgumentParser(add_help=False)
  parent.add_argument('-p', '--pos', action='store_true')

  # Subparsers
  sp = p.add_subparsers(help='use <subcommand> -h for further help', title=
    'subcommands')

  # Flat
  p1 = sp.add_parser(cmds[0], parents=[parent])
  p1.add_argument('input', nargs='+', action=InputAction)
  f = cmds[0] + '.html'
  p1.add_argument('-o', '--out', action='store', default=f)
  p1.add_argument('-d', '--diro', action='store', default='entries')
  p1.set_defaults(func=partial(mux, flat))

  # Classified
  p2 = sp.add_parser(cmds[1], parents=[parent])
  p2.add_argument('input', nargs='+', action=InputAction)
  f = cmds[1] + '.html'
  p2.add_argument('-o', '--out', action='store', default=f)
  p2.add_argument('-d', '--diro', action='store', default='entries')
  p2.set_defaults(func=partial(mux, classified))

  # Sections
  p3 = sp.add_parser(cmds[2], parents=[parent])
  p3.add_argument('input', nargs='+', action=InputAction)
  f = cmds[2] + '.html'
  p3.add_argument('-o', '--out', action='store', default=f)
  p3.add_argument('-d', '--diro', action='store', default='entries')
  p3.set_defaults(func=partial(mux, sections))

  # Two-level
  p4 = sp.add_parser(cmds[3], parents=[parent])
  p4.add_argument('input', nargs='+', action=InputAction)
  f = cmds[3] + '.html'
  p4.add_argument('-o', '--out', action='store', default=f)
  p4.add_argument('-d', '--diro', action='store', default='entries')
  p4.set_defaults(func=partial(mux, two_level))

  # Latex
  p5 = sp.add_parser(cmds[4], parents=[parent])
  p5.add_argument('input', action=InputAction)
  f = cmds[4] + '.tex'
  p5.add_argument('-o', '--out', action='store', default=f)
  p5.set_defaults(func=partial(mux, latex))

  # Latex 2
  p6 = sp.add_parser(cmds[5], parents=[parent])
  p6.add_argument('input', action=InputAction)
  f = cmds[5] + '.tex'
  p6.add_argument('-o', '--out', action='store', default=f)
  p6.set_defaults(func=partial(mux, latex2))

  # Latex 3
  p7 = sp.add_parser(cmds[6], parents=[parent])
  p7.add_argument('input', action=InputAction)
  f = cmds[6] + '.tex'
  p7.add_argument('-o', '--out', action='store', default=f)
  p7.set_defaults(func=partial(mux, latex3))

  # Incantations
  p8 = sp.add_parser(cmds[7], description='Produce tables comparing the\
    effectiveness of the incantations')
  p8.add_argument('input', action=InputAction, help='log (text or pickle)')
  f = cmds[7]
  p8.add_argument('-o', '--out', action='store', default=f,
    help='output file basename (instead of default name)')
  p8.set_defaults(func=partial(mux, incantations))

  # Incantations flat
  p9 = sp.add_parser(cmds[8], description='Produce flat tables comparing the\
    effectiveness of the incantations')
  p9.add_argument('input', action=InputAction, help='log (text or pickle)')
  f = cmds[8]
  p9.add_argument('-o', '--out', action='store', default=f,
    help='output file basename (instead of default name)')
  p9.set_defaults(func=partial(mux, incantations_flat))

  # Incantations html
  p10 = sp.add_parser(cmds[9], description='Produce flat html tables comparing\
    the effectiveness of the incantations')
  p10.add_argument('input', action=InputAction, help='log (text or pickle)')
  f = cmds[9]
  p10.add_argument('-o', '--out', action='store', default=f,
    help='output file basename (instead of default name)')
  p10.add_argument('-d', '--diro', action='store', default='entries-inc')
  p10.set_defaults(func=partial(mux, incantations_html_flat))

  return p

if __name__ == "__main__":
  if len(sys.argv) == 1:
    sys.argv += ['-h']
  cmd = sys.argv[1]
  ma.setup_err_handling('log2tbl.py')
  cmds = ['flat', 'classified', 'sections', 'two-level', 'latex', 'latex2',
    'latex3', 'incantations', 'incantations-flat', 'incantations-html']
  p = get_cmdline_parser(cmds)
  if cmd not in cmds:
    p.print_help()
    sys.exit(2)
  print('cmd: ' + cmd)
  pr = p.parse_args()
  pr.func(pr)

