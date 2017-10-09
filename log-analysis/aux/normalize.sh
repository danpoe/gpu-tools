#!/bin/bash

# Normalize and pickle textual litmus logs
#
# ./normalize.sh [-i] [<dir>]

set -e

l2l=./log2log.py
l2t=./log2tbl.py

OPT=
D=results

if [ $1 = '-i' ]; then
  OPT=-i
  if [ ! -z $2 ]; then
    D=$2
  fi
elif [ ! -z $1 ]; then
  D=$1
fi


for f in "$D"/*.txt
do
  if [ ! -f $f.norm ]; then
    $l2l $OPT normalize $f.norm $f
    $l2l $OPT pickle $f.pkl $f.norm
    continue
  fi
  if [ ! -f $f.pkl ]; then
    $l2l $OPT pickle $f.pkl $f.norm
  fi
done

