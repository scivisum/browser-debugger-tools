#!/bin/sh
helpFunction()
{
   echo ""
   echo "Usage: $0 -t test type"
   echo -e "\t-t Test type unit/integration/e2e"
   exit 1
}
while getopts ":t:" o; do
    case "$o" in
        t)
            type=$OPTARG
            ;;
        *)
            helpFunction
            ;;
    esac
done
if [ -z "$type" ]; then
   echo "Specify a test type";
   helpFunction
fi
echo "Running ${type}tests"
python -m unittest discover ./tests/"$type"tests
