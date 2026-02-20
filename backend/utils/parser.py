import re


def extract_line(logs):

    match = re.search(r"line (\d+)", logs)

    if match:
        return int(match.group(1))

    return 0
