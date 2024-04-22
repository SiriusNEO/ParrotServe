#!/bin/sh

# warn: rm result
rm result.txt
touch result.txt

for reqs in {5..25..5}
do
    for capacity in {2048..12288..2048}
    do
    echo "Run with capacity: $capacity, reqs: $reqs"
    echo "capacity: $capacity, reqs: $reqs" >> result.txt
    bash run_vllm.sh $capacity $reqs
    python3 parse_log_vllm.py >> result.txt
    sleep 5
    done
done

# Plot the results
python3 plot.py