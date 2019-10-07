#!/bin/sh
ps fuxa|egrep '[[:space:]]+\\_ python.*\./server'|awk '{print $2}'|xargs kill -9
