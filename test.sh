#!/bin/bash
images=$(docker image list)
for VERS in "106-3.8" "112-3.11"
do
  matches=$(echo "$images" |grep browser-debugger-tools-test:$VERS)
  echo "########### Testing Dockerfile-$VERS ###########"
  if [ "$1" == "--build" ] || [ "$matches" == "" ]; then
    docker build -f Dockerfile-$VERS -t browser-debugger-tools-test:$VERS .
  fi
done
for VERS in "106-3.8" "112-3.11"
do
  docker run -v $PWD/tests:/code/tests -v $PWD/browserdebuggertools:/code/browserdebuggertools \
    browser-debugger-tools-test:$VERS tini -- xvfb-run pytest .
done
