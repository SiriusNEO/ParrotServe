#!/bin/sh

rm *.log -rf

export VLLM_CAPACITY=4096
bash fastchat/launch_vllm.sh

export OPENAI_API_BASE=http://localhost:8000/v1
export OPENAI_API_KEY=EMPTY

sleep 1

python3 bench_multi_agents_vllm.py > result_vllm_lat.log

sleep 1

bash ../../scripts/kill_all_fastchat_servers.sh