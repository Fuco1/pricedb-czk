#!/usr/bin/env bash

# Parse options using getopt
OPTIONS=$(getopt -o '' --long from:,to: -- "$@")
if [ $? -ne 0 ]; then
    echo "Usage: $0 [--from NEW_FROM] [--to NEW_TO] file"
    exit 1
fi

eval set -- "$OPTIONS"

from_currency=""
to_currency=""

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

file="$1"

if [[ -z "$file" ]]; then
    echo "Usage: $0 [--from NEW_FROM] [--to NEW_TO] file"
    exit 1
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

awk -v from="$from_currency" -v to="$to_currency" '{
    if (from != "") $3 = from;
    if (to   != "") $5 = to;
    print
}' OFS=" " "$file" > "$newfile"

echo "Modified file saved as: $newfile"
