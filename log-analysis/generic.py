
####################
# Helper functions #
####################

def w_str(out, s):
  f = open(out, 'w')
  f.write(s)
  f.close()

# Convert number to string containing K, M, etc. suffixes
def convert(n):
  assert(n >= 0)
  n = int(n)
  assert(type(n) is int)
  suffixes = ['', 'K', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y']
  i = 0
  while (n >= 1000):
    i += 1
    n /= 1000
  if n >= 10:
    n = round(n)
  else:
    n = round(n, 1)
  s = str(n) + suffixes[i]
  assert(not(n != 0 and s == '0'))
  return s

# Interleave the two lists to produce a new list
def interleave(l1, l2, n):
  l = list()
  while l1 or l2:
    chunk1 = l1[:n]
    l1 = l1 [n:]
    chunk2 = l2[:n]
    l2 = l2[n:]
    l += chunk1 + chunk2
  return l

def unzip(l):
  return zip(*l)

def listify(l):
  if type(l) != list:
    l = [l]
  return l

def itemify(l):
  if type(l) == list:
    assert(len(l) == 1)
    return l[0]
  return l

# Cut and left justify
def ljcut(s, n):
  s = s[:n]
  return s.ljust(n)

def dupchk(l):
  s = set(l)
  if len(s) != len(l):
    return True
  return False

########################
# Type/instance checks #
########################

# Check if all elements in the list have the specified type; always holds for
# empty lists
def lty(l, t):
  if type(l) != list:
    return False
  for el in l:
    if type(el) != t:
      return False
  return True

# Same as above for tuples
def tty(tup, t):
  lty(tup, t)

def lins(l, i):
  if type(l) != list:
    return False
  for el in l:
    if not isinstance(el, i):
      return False
  return True

def tins(tup, i):
  lins(tup, i)

def either_ty(a, t1, t2):
  return type(a) == t1 or type(a) == t2

