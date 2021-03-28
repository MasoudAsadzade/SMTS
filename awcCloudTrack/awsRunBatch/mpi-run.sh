#!/bin/bash
/usr/sbin/sshd -D &

PATH="$PATH:/opt/openmpi/bin/"
BASENAME="${0##*/}"
log () {
  echo "${BASENAME} - ${1}"
}
HOST_FILE_PATH="/tmp/hostfile"
#aws s3 cp $S3_INPUT $SCRATCH_DIR
#tar -xvf $SCRATCH_DIR/*.tar.gz -C $SCRATCH_DIR

sleep 2
echo main node: ${AWS_BATCH_JOB_MAIN_NODE_INDEX}
echo this node: ${AWS_BATCH_JOB_NODE_INDEX}
echo Downloading problem from S3: ${COMP_S3_PROBLEM_PATH}

if [[ "${COMP_S3_PROBLEM_PATH}" == *".xz" ]];
then
  aws s3 cp s3://${S3_BKT}/${COMP_S3_PROBLEM_PATH} test.cnf.xz
  unxz test.cnf.xz
else
  aws s3 cp s3://${S3_BKT}/${COMP_S3_PROBLEM_PATH} test.cnf
fi

# Set child by default switch to main if on main node container
NODE_TYPE="child"
if [ "${AWS_BATCH_JOB_MAIN_NODE_INDEX}" == "${AWS_BATCH_JOB_NODE_INDEX}" ]; then
  log "Running synchronize as the main node"
  NODE_TYPE="main"
fi
sleep 2
# wait for all nodes to report
wait_for_nodes () {
  log "Running as server node"
  sleep 2
  touch $HOST_FILE_PATH
  ip=$(/sbin/ip -o -4 addr list eth0 | awk '{print $4}' | cut -d/ -f1)

  availablecores=$(nproc)
  log "Server details (ip:cores) -> $ip:$availablecores"
  log "server IP: $ip"
  echo "$ip slots=$availablecores" >> $HOST_FILE_PATH${AWS_BATCH_JOB_NODE_INDEX}
  #echo "$ip" >> $HOST_FILE_PATH
  lines=$(ls -dq /tmp/hostfile* | wc -l)

  while [ "${AWS_BATCH_JOB_NUM_NODES}" -gt "${lines}" ]
    do
      #cat $HOST_FILE_PATH
      lines=$(ls -dq /tmp/hostfile* | wc -l)
      log "$lines out of $AWS_BATCH_JOB_NUM_NODES nodes joined, check again in 1 second"
      sleep 1
  #    lines=$(sort $HOST_FILE_PATH|uniq|wc -l)
    done

  # All of the hosts report their IP and number of processors. Combine all these
  # into one file with the following script:
  python3 SMTS/awcCloudTrack/awsRunBatch/make_combined_hostfile.py ${ip}
  cat SMTS/awcCloudTrack/awsRunBatch/combined_hostfile
  mpirun --mca btl_tcp_if_include eth0 --allow-run-as-root -np 1 --hostfile $HOST_FILE_PATH${AWS_BATCH_JOB_NODE_INDEX}  --app SMTS/awcCloudTrack/awsRunBatch/run_aws_osmt.sh "SMTS/hpcClusterBenchs/${COMP_S3_PROBLEM_PATH}"
#  IFS=$'\n' read -d '' -r -a workerNodes < SMTS/awcCloudTrack/awsRunBatch/combined_hostfile
#  i=0
#  for worker_ip in "${workerNodes[@]}"
#  do
#  #  read -ra node_ip <<<${worker_ip}
#    i=$((${i} + 1))
#    echo  "${worker_ip}"
#    echo "$ip" >>  SMTS/awcCloudTrack/awsRunBatch/"${worker_ip}"
#    mpirun --mca btl_tcp_if_include eth0 --allow-run-as-root -np 1 --hostfile SMTS/awcCloudTrack/awsRunBatch/"${worker_ip}"  --app run_aws_osmt.sh SMTS/hpcClusterBench/${COMP_S3_PROBLEM_PATH}${i}
#  done
  #  if  [ "${node_ip[0]}" == "$ip" ]
  #  then
  #    echo "SMTS Server is running..."

  #    sleep 2
  #  else
   #   mpirun --mca btl_tcp_if_include eth0 --allow-run-as-root -np 1 --hostfile SMTS/awcCloudTrack/awsRunBatch/"${node_ip[0]}" SMTS/build/solver_opensmt -s ${node_ip[0]}:3000 &
   #   sleep 1
   # fi
  ps -ef | grep sshd
  tail -f /dev/null

}

# Fetch and run a script
report_to_master () {
  # get own ip
  ip=$(/sbin/ip -o -4 addr list eth0 | awk '{print $4}' | cut -d/ -f1)
  availablecores=$(nproc)

  log "I am a opensmt child node${AWS_BATCH_JOB_NODE_INDEX} -> $ip:$availablecores, reporting to the server node -> ${AWS_BATCH_JOB_MAIN_NODE_PRIVATE_IPV4_ADDRESS}"

  echo "$ip slots=$availablecores" >> $HOST_FILE_PATH${AWS_BATCH_JOB_NODE_INDEX}
  ping -c 3 ${AWS_BATCH_JOB_MAIN_NODE_PRIVATE_IPV4_ADDRESS}
  until scp $HOST_FILE_PATH${AWS_BATCH_JOB_NODE_INDEX} ${AWS_BATCH_JOB_MAIN_NODE_PRIVATE_IPV4_ADDRESS}:$HOST_FILE_PATH${AWS_BATCH_JOB_NODE_INDEX}
  do
    echo "Sleeping 2 seconds and trying again"
    sleep 2
  done
  mpirun --mca btl_tcp_if_include eth0 --allow-run-as-root -np 1 --hostfile $HOST_FILE_PATH${AWS_BATCH_JOB_NODE_INDEX}  --app SMTS/awcCloudTrack/awsRunBatch/run_aws_osmt.sh "SMTS/hpcClusterBenchs/${COMP_S3_PROBLEM_PATH}"
  ps -ef | grep sshd
  tail -f /dev/null
}
##
# Main - dispatch user request to appropriate function
log $NODE_TYPE
case $NODE_TYPE in
  main)
    wait_for_nodes "${@}"
    ;;

  child)
    report_to_master "${@}"
    ;;

  *)
    log $NODE_TYPE
    usage "Could not determine node type. Expected (main/child)"
    ;;
esac