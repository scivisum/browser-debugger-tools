#!/bin/sh
helpFunction()
{
   echo ""
   echo "Usage: $0 -t test type"
   echo -e "\t-t Test type unit/integration/e2e"
   exit 1
}

getopts "t" CONFIG
if [ -z "$CONFIG" ]
then
   echo "Specify a test type";
   helpFunction
fi
python -m unittest discover "./tests/$CONFIGtests"
