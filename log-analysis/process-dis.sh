#!/bin/bash

# Produce tables for distilled tests
#
# ./process-dis.sh [<dir>]

l2l=./log2log.py
l2t=./log2tbl.py

R=$1
if [ -z $R ]; then
  R=results-dis
fi

# Fix names (both PTX and OpenCL logs)
echo '*** Fixing names'
for f in $R/*.txt
do
  sed 's/^GPU_PTX \([^-]*\)-\([^-]*\)/GPU_PTX \1_\2/g' $f > $f.sed
  sed -i 's/^GPU_PTX \([^-]*\)-\([^-]*\)/GPU_PTX \1_\2/g' $f.sed
  sed -i 's/^RACE_OPENCL \([^-]*\)-\([^-]*\)/RACE_OPENCL \1_\2/g' $f.sed
  sed -i 's/^RACE_OPENCL \([^-]*\)-\([^-]*\)/RACE_OPENCL \1_\2/g' $f.sed
done

echo '*** Normalizing AMD logs'
for f in $R/turks*.sed $R/tahiti*.sed
do
  if [ ! -f $f.norm ]; then
    $l2l normalize -i $f.norm $f
    $l2l pickle -i $f.pkl $f.norm
    continue
  fi
  if [ ! -f $f.pkl ]; then
    $l2l pickle -i $f.pkl $f.norm
  fi
done

echo '*** Select best from AMD logs'
for f in $R/turks*.pkl $R/tahiti*.pkl
do
  d=$(dirname $f)
  n=$(basename $f .pkl)
  $l2l best $d/$n.best.pkl $f
done

echo '*** Normalizing Nvidia logs'
for f in $R/GTX*.sed $R/Tesla*.sed
do
  if [ ! -f $f.norm ]; then
    $l2l normalize $f.norm $f
    $l2l pickle $f.pkl $f.norm
    continue
  fi
  if [ ! -f $f.pkl ]; then
    $l2l pickle $f.pkl $f.norm
  fi
done

# Create sum
echo '*** Creating Nvidia sum logs'
if [ ! -f $R/sum-dis-ptx.pkl ]; then
  $l2l sum sum-dis-ptx.pkl $R/GTX*.pkl $R/Tesla*.pkl
fi
echo '*** Creating AMD sum logs'
if [ ! -f $R/sum-dis-opencl.pkl ]; then
  $l2l sum sum-dis-opencl.pkl $R/tahiti*.best.pkl $R/turks*.best.pkl
fi

echo '*** Producing tables'
$l2t flat -o distilled-ptx.html -d entries-dis $R/GTX*.pkl $R/Tesla*.pkl
$l2t flat -o distilled-opencl.html -d entries-dis $R/tahiti*.best.pkl $R/turks*.best.pkl

