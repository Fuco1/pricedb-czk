#!/usr/bin/env bash

# Parse options using getopt
OPTIONS=$(getopt -o '' --long from:,to:,to-prefix: -- "$@")
if [ $? -ne 0 ]; then
    echo "Usage: $0 [--from NEW_FROM] [--to NEW_TO] [--to-prefix PREFIX] file1 [file2 ...]"
    exit 1
fi

eval set -- "$OPTIONS"

from_currency=""
to_currency=""
to_prefix=""

while true; do
    case "$1" in
        --from)
            from_currency="$2"
            shift 2
            ;;
        --to)
            to_currency="$2"
            shift 2
            ;;
        --to-prefix)
            to_prefix="$2"
            shift 2
            ;;
        --)
            shift
            break
            ;;
        *)
            echo "Invalid option: $1"
            exit 1
            ;;
    esac
done

# Check mutual exclusivity
if [[ -n "$to_currency" && -n "$to_prefix" ]]; then
    echo "Error: --to and --to-prefix cannot be used together."
    exit 1
fi

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 [--from NEW_FROM] [--to NEW_TO] [--to-prefix PREFIX] file1 [file2 ...]"
    exit 1
fi

for file in "$@"; do
    if [[ ! -f "$file" ]]; then
        echo "Skipping '$file' (not found)"
        continue
    fi

    # Extract filename and extension
    filename="${file%.*}"
    extension="${file##*.}"

    # If no extension (filename == extension), just append '-modded'
    if [[ "$filename" == "$extension" ]]; then
        newfile="${filename}-modded"
    else
        newfile="${filename}-modded.${extension}"
    fi

    awk -v from="$from_currency" -v to="$to_currency" -v prefix="$to_prefix" '{
        if (from != "") $3 = from;
        if (to != "") $5 = to;
        if (prefix != "") {
            $4 = prefix $4;  # prepend prefix to rate
            $5 = "";          # remove original currency code
        }
        print
    }' OFS=" " "$file" > "$newfile"

    echo "Modified file saved as: $newfile"
done
