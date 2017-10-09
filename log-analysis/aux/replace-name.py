#!/usr/bin/env python3

import sys
import re

def run(s):
  newname = ''
  ls = s.splitlines()
  out = []

  for l in ls:
    if l.startswith('% Results'):
      mo = re.search(r'/[^ \t%]+.litmus', l)
      assert(mo)
      s = mo.group(0)
      assert(s[0] == '/')
      s = s[1:]
      s = s.replace('-', '_')
      assert(s.endswith('.litmus'))
      s = s.replace('.litmus', '')
      newname = s
      out.append(l)
      continue
    if l.startswith('RACE_OPENCL'):
      out.append('RACE_OPENCL ' + newname)
      continue
    out.append(l) 

  s = '\n'.join(out)
  print(s)

if __name__ == "__main__":
  f = sys.argv[1]
  f = open(f, 'r')
  s = f.read()
  f.close()
  run(s)

