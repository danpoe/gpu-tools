#!/bin/bash

set -e

rm -fr __pycache__

rm -f *.pkl *.html *.tex
rm -f *.aux *.log *.pdf

# Remove result of processing textual logs
rm -f results/*.norm results/*.pkl
rm -f results-inc/*.norm results-inc/*.pkl
rm -f results-dis/*.norm results-dis/*.pkl results-dis/*.sed

# Remove litmus tests
find entries -name '*.txt' 2> /dev/null | xargs rm -f
find entries-dis -name '*.txt' 2> /dev/null | xargs rm -f
find entries-inc -name '*.txt' 2> /dev/null | xargs rm -f

cd test
./clean.sh
cd ..

