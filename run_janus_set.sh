#!/bin/bash

pip install .
echo
echo

####################################################################################################
# RUN INFERANCE (DISABLE PHASE 3 BEFORE RUNNING)
####################################################################################################

# for i in {1..6}; do
#   echo "using configs/config-$i.json"
#   exec_v2s --config="configs/config-$i.json" &
# done

# wait


####################################################################################################
# RUN EMULATOR (DISABLE PHASE 1 & 2 BEFORE RUNNING)
####################################################################################################

format_time() {
    local total_seconds=$1
    local hours=$((total_seconds / 3600))
    local minutes=$(( (total_seconds % 3600) / 60 ))
    local seconds=$((total_seconds % 60))
    printf "%02d:%02d:%02d\n" $hours $minutes $seconds
}

start_time=$(date +%s)
start=91
end=121
for i in $(seq $start $end); do
  current_time=$(date +%s)
  elapsed_time=$((current_time - start_time))
  total_loops=$((end - start))
  if [ $i -gt 1 ]; then
    avg_time_per_loop=$(bc <<< "scale=2; $elapsed_time / ( $i - 1 )")
    # estimated_remaining_time=$(bc <<< "scale=2; $avg_time_per_loop * ($total_loops - $i + 1)")
    estimated_remaining_time=$(printf "%.0f" $(bc <<< "$avg_time_per_loop * ($total_loops - $i + 1)"))
  else
    estimated_remaining_time=0
  fi

  elapsed_time_f=$(format_time $elapsed_time)
  estimated_remaining_time_f=$(format_time $estimated_remaining_time)
  current_video=$((i - start + 1))
  echo "Processing Video $i/$total_loops (Elapsed time: ${elapsed_time_f} - Estimated remaining time: ${estimated_remaining_time_f})"

  # Start the emulator
  echo "  1. Starting the emulator"
  echo "      ├ Wiping data..."
  /mnt/c/Users/Isaac/AppData/Local/Android/Sdk/emulator/emulator.exe -avd Nexus_5X_API_24 -wipe-data > /dev/null 2>&1 &
  
  # Wait for the emulator to start responding to adb
  echo "      ├ Waiting for emulator to connect..."
  /mnt/c/Users/Isaac/AppData/Local/Android/Sdk/platform-tools/adb.exe wait-for-device
  sleep 2
  echo "      └ Device is fully booted!"
  
  # Run the configuration
  echo "  2. Running emulation"
  echo "      ├ Enabling touch indicator..."
  /mnt/c/Users/Isaac/AppData/Local/Android/Sdk/platform-tools/adb.exe shell settings put system show_touches 1 
  echo "      ├ Running V2S..."
  exec_v2s --config="configs/${i}-config.json" > /dev/null 2>&1
  echo "      └ Done!"
  
  # Shut down the device
  echo "  3. Shutting down device"
  /mnt/c/Users/Isaac/AppData/Local/Android/Sdk/platform-tools/adb.exe -s emulator-5554 emu kill > /dev/null
  
  # Wait for pricess to exit
  while pgrep -f "emulator.*-avd Nexus_5X_API_24" > /dev/null; do
    echo "      ├ Waiting for emulator to shut down..."
    sleep 5
  done
  echo "      └ Device is fully shut down!"

  echo ""
done