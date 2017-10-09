#!/bin/bash

# Produce html tables for full and positive results
#
# ./process.sh [<dir>]

set -e

l2l=./log2log.py
l2t=./log2tbl.py

D=$1

if [ -z "$D" ]; then
  D=results
fi

# Normalize and pickle logs
N=aux/normalize.sh
./$N $D

# Create sum
if [ ! -f sum.pkl ]; then
  $l2l sum sum.pkl $D/gtx*.pkl $D/tesla*.pkl
fi

# Produce full tables
$l2t flat sum.pkl $D/gtx*.pkl $D/tesla*.pkl
$l2t sections sum.pkl $D/gtx*.pkl $D/tesla*.pkl
$l2t classified sum.pkl $D/gtx*.pkl $D/tesla*.pkl
$l2t two-level sum.pkl $D/gtx*.pkl $D/tesla*.pkl

# Produce tables of positive results only
$l2t flat -p -o flat-pos.html sum.pkl $D/gtx*.pkl $D/tesla*.pkl
$l2t sections -p -o sections-pos.html sum.pkl $D/gtx*.pkl $D/tesla*.pkl
$l2t classified -p -o classified-pos.html sum.pkl $D/gtx*.pkl $D/tesla*.pkl
$l2t two-level -p -o two-level-pos.html sum.pkl $D/gtx*.pkl $D/tesla*.pkl

