#!/usr/bin/python3
from common.merge_logs import process_and_merge
import argparse

if __name__ == "__main__":
  argparser = argparse.ArgumentParser(description="merge logs")
  argparser.add_argument(
        '--raw_log',
        type=str,
        required=True,
        help='raw log path'
  )
  argparser.add_argument(
        '--merged_log',
        type=str,
        required=True,
        help='merged log path'
  )
  args = argparser.parse_args()
  process_and_merge(args.raw_log, args.merged_log)