#!/bin/bash

# Gather all tex files in the current directory and produce a combined file
#
# ./gather-tex.sh [<out>]

set -e

OUT=$1

if [ -z "$OUT" ]; then
  OUT=inc.tex
fi

PRE="\
\documentclass[a4paper,10pt]{article}

\usepackage[usenames,dvipsnames,svgnames,table]{xcolor}
\usepackage{tabularx}
\usepackage{booktabs}
\usepackage[left=0cm,right=0cm]{geometry}

\begin{document}
\pagenumbering{gobble}
"

POST="\
\end{document}
"

echo "$PRE" > "$OUT"

shopt -s extglob

for n in $(ls !(inc.tex|!(*.tex)))
do
  echo "\begin{center}" >> "$OUT"
  cat "$n" >> "$OUT"
  echo "\newpage" >> "$OUT"
  echo "\end{center}" >> "$OUT"
  echo "% --------------------" >> "$OUT"
  echo >> "$OUT"
done

echo "$POST" >> "$OUT"

