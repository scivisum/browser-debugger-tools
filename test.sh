#!/bin/bash
images=$(docker image list)
if [ "$1" == "--build" ] || [ -z "$1" ]; then
  echo "No matchings provided"
  exit 1
fi
for VERS in "112-3.11" "106-3.8"
do
  matches=$(echo "$images" |grep browser-debugger-tools-test:$VERS)
  if [ "$2" == "--build" ] || [ "$matches" == "" ]; then
      echo "########### BUILDING Dockerfile-$VERS ###########"
    docker build -f Dockerfile-$VERS -t browser-debugger-tools-test:$VERS .
  fi
done
for VERS in "106-3.8" "112-3.11"
do
  echo "########### TESTING Dockerfile-$VERS ###########"
  docker run --init -v $PWD/tests:/code/tests -v $PWD/browserdebuggertools:/code/browserdebuggertools \
    -v /tmp/screenshots:/tmp/screenshots \
    browser-debugger-tools-test:$VERS xvfb-run pytest "/code/tests/$1" -s
done
