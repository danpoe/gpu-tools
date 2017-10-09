#!/bin/bash

# Produce incantation tables
#
# ./process-inc.sh <flat|classified|html> [<dir>]

set -e

function usage {
  echo "Usage:" >&2
  echo "  ./process-inc.sh (flat|classified|html)" >&2
  echo
  echo "* flat: produce flat listing of tests"
  echo "* classified: divide tests into sections according to axioms"
  echo "* html: produce html incantation tables"
}

if [ $# -ne 1 ] && [ $# -ne 2 ]; then
  usage
  exit 1
fi

CMD=$1
if [ "$CMD" != flat ] && [ "$CMD" != classified ] && [ "$CMD" != html ]; then
  usage
  exit 1
fi

R=$2
if [ -z $R ]; then
  R=results-inc
fi

declare -A map
map=(["flat"]="incantations-flat" ["classified"]="incantations" ["html"]=\
"incantations-html")

declare -A ext
ext=(["flat"]="tex" ["classified"]="tex" ["html"]="html")

l2l=./log2log.py
l2t=./log2tbl.py

# Normalize and pickle incantation logs
N=aux/normalize.sh
./$N -i $R

# Produce incantation tables
for f in $R/*.pkl
do
  out=$(basename $f .pkl)
  out=$(basename $out .norm)
  out=$(basename $out .txt)
  $l2t "${map[$CMD]}" -o "$out.${ext[$CMD]}" $f
done

