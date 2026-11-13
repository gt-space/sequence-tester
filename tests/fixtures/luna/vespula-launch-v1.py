# launch sequence, start at T - 10
import time
print('Launch Sequence has begun')

# target pressures
ftpt_target = 416*psi # psia
otpt_target = 353*psi # psia
fswitch_target = 2500*psi # psia, COPV pressure to open FSWV
oswitch_target = 2500*psi # psia, COPV pressure to open OSWV

# generic variables
upRan = 2*psi # psi, upper range for bang bang algo
lowRan = 3*psi # psi, lower range for bang bang algo
wait_timing = 5 # ms, for loop check timing

# valve timings
fmv_time = 0.06 # s, observed FMV actuation time
omv_time = 0.125 # s, observed OMV actuation time

# lead times
lox_open_lead = 0.01 # s, targeted lox lead time
lox_close_lead = 0.1 # s, close OMV before FMV to avoid ox rich

fmv_open_wait = omv_time+lox_open_lead-fmv_time # wait between opening omv and fmv
lox_close_wait = omv_time+lox_close_lead-fmv_time # time to wait after closing omv

# T-X times/durations
pre_time = 10 # s, T-10 press tanks
igniter_start = 2.5 # s, T-2.5 igniters on
sense_window = 1.5 # s, time for sense wire to break
press_time = pre_time - igniter_start # T-7.5 time to start igniters
igniter_lead = 1.5 # s, let igniter heat up

# T+X times/durations
lug1_arm = 2 # s, T+2 arm lug 1 (IT3)
lug1_time = 2.1 # s, T+2.1 eject lug 1, arm lug 2 (IT2?)
lug2_time = 2.6 # s, T+2.6 eject lug 2, turn off lug 1
lug2_off = 3.1 # s, T+3.1 turn off lug 2
fire_time = 26.2 # s, time we are firing for
post_fire_press = 40 # s, T+40 end tank press
fuel_purge_time = 55 # s, T+55 open FMV
lox_purge_time = 65 # s, T+65 open OMV
vent_open_time = 75 # s, T+75 open tank vents
prvnt_open_time = 78 # s, T+78 open PRVNT
pnvnt_open_time = 80 # s, T+80 open PNVNT

# sense wire check
if Sense.read() < 3.5*V:
	print('The sense wire is not properly connected, exiting sequence')
	stop()

# initialize BB valve states (hardcoded)
FBB.close()
FBBopen = False
OBB.close()
OBBopen = False
wait_for(wait_timing*ms)

# initialize switch valve states (hardcoded)
FSWV.close()
FSWVclose = True
OSWV.close()
OSWVclose = True

# start sequence
start_time = time.time()

# T-10 press tanks
while time.time() < start_time + press_time:
	# check pressures
	currFTPT = FTPT.read()
	currOTPT = OTPT.read()
	# BB algo
	if FBBopen and currFTPT > ftpt_target + upRan:
		FBB.close()
		FBBopen = False
	elif (not FBBopen) and currFTPT < ftpt_target - lowRan:
		FBB.open()
		FBBopen = True
	if OBBopen and currOTPT > otpt_target + upRan:
		OBB.close()
		OBBopen = False
	elif (not OBBopen) and currOTPT < otpt_target - lowRan:
		OBB.open()
		OBBopen = True
	wait_for(wait_timing*ms)
	
# T-2.5 igniter on
send_reco_launch()
wait_for(20*ms)
if not reco_recvd_launch()
	print('Reco did not receive the timer, exiting sequence')
	FBB.close()
	OBB.close()
	stop()
IGNITER.open()
# check sense wire
while time.time() < start_time + press_time + sense_window:
	# check pressures
	currFTPT = FTPT.read()
	currOTPT = OTPT.read()
	# BB algo
	if FBBopen and currFTPT > ftpt_target + upRan:
		FBB.close()
		FBBopen = False
	elif (not FBBopen) and currFTPT < ftpt_target - lowRan:
		FBB.open()
		FBBopen = True
	if OBBopen and currOTPT > otpt_target + upRan:
		OBB.close()
		OBBopen = False
	elif (not OBBopen) and currOTPT < otpt_target - lowRan:
		OBB.open()
		OBBopen = True
	if Sense.read() < 0.5*V:
		print('The sense wire has broken')
		break
	wait_for(wait_timing*ms)

# check if igniter failed
if Sense.read() > 3.5*V:
	print('The sense wire did not break, exiting sequence')
	IGNITER.close()
	OBB.close()
	FBB.close()
	stop()

# T-1.5 define ignition time and let igniter heat
ignition_time = time.time()
while time.time() < ignition_time + igniter_lead:	
	# check pressures
	currFTPT = FTPT.read()
	currOTPT = OTPT.read()
	# BB algo
	if FBBopen and currFTPT > ftpt_target + upRan:
		FBB.close()
		FBBopen = False
	elif (not FBBopen) and currFTPT < ftpt_target - lowRan:
		FBB.open()
		FBBopen = True
	if OBBopen and currOTPT > otpt_target + upRan:
		OBB.close()
		OBBopen = False
	elif (not OBBopen) and currOTPT < otpt_target - lowRan:
		OBB.open()
		OBBopen = True
	wait_for(wait_timing*ms)

# T-0.135 open OMV
OMV.open()

# loop for time before opening FMV
while time.time() < ignition_time + igniter_lead + fmv_open_wait:	
	# check pressures
	currFTPT = FTPT.read()
	currOTPT = OTPT.read()
	# BB algo
	if FBBopen and currFTPT > ftpt_target + upRan:
		FBB.close()
		FBBopen = False
	elif (not FBBopen) and currFTPT < ftpt_target - lowRan:
		FBB.open()
		FBBopen = True
	if OBBopen and currOTPT > otpt_target + upRan:
		OBB.close()
		OBBopen = False
	elif (not OBBopen) and currOTPT < otpt_target - lowRan:
		OBB.open()
		OBBopen = True
	wait_for(wait_timing*ms)

# T-0.06 open FMV 
FMV.open()

# loop for time before FMV fully open
while time.time() < ignition_time + igniter_lead + fmv_open_wait + fmv_time:
	# check pressures
	currFTPT = FTPT.read()
	currOTPT = OTPT.read()
	# BB algo
	if FBBopen and currFTPT > ftpt_target + upRan:
		FBB.close()
		FBBopen = False
	elif (not FBBopen) and currFTPT < ftpt_target - lowRan:
		FBB.open()
		FBBopen = True
	if OBBopen and currOTPT > otpt_target + upRan:
		OBB.close()
		OBBopen = False
	elif (not OBBopen) and currOTPT < otpt_target - lowRan:
		OBB.open()
		OBBopen = True
	wait_for(wait_timing*ms)

# T-0: begin fire
print('Main Valves have Opened and Fire has begun')
IGNITER.close()
fire_start = time.time()

# launch lugs
while time.time() < fire_start + lug1_arm:
	# check pressures
	currFTPT = FTPT.read()
	currOTPT = OTPT.read()
	# BB algo
	if FBBopen and currFTPT > ftpt_target + upRan:
		FBB.close()
		FBBopen = False
	elif (not FBBopen) and currFTPT < ftpt_target - lowRan:
		FBB.open()
		FBBopen = True
	if OBBopen and currOTPT > otpt_target + upRan:
		OBB.close()
		OBBopen = False
	elif (not OBBopen) and currOTPT < otpt_target - lowRan:
		OBB.open()
		OBBopen = True
	wait_for(wait_timing*ms)

# T+2 arm lug 1
launch_lug_arm('sam-31',true)

while time.time() < fire_start + lug1_time:
	# check pressures
	currFTPT = FTPT.read()
	currOTPT = OTPT.read()
	# BB algo
	if FBBopen and currFTPT > ftpt_target + upRan:
		FBB.close()
		FBBopen = False
	elif (not FBBopen) and currFTPT < ftpt_target - lowRan:
		FBB.open()
		FBBopen = True
	if OBBopen and currOTPT > otpt_target + upRan:
		OBB.close()
		OBBopen = False
	elif (not OBBopen) and currOTPT < otpt_target - lowRan:
		OBB.open()
		OBBopen = True
	wait_for(wait_timing*ms)

# T+2.1 eject lug 1, arm lug 2
launch_lug_detonate('sam-31',true)
launch_lug_arm('sam-32',true)

while time.time() < fire_start + lug2_time:
	# check pressures
	currFTPT = FTPT.read()
	currOTPT = OTPT.read()
	# bang bang algorithm
	if FBBopen and currFTPT > ftpt_target + upRan:
		FBB.close()
		FBBopen = False
	elif (not FBBopen) and currFTPT < ftpt_target - lowRan:
		FBB.open()
		FBBopen = True
	if OBBopen and currOTPT > otpt_target + upRan:
		OBB.close()
		OBBopen = False
	elif (not OBBopen) and currOTPT < otpt_target - lowRan:
		OBB.open()
		OBBopen = True
	wait_for(wait_timing*ms)

# T+2.6 eject lug 2, turn off lug 1
launch_lug_detonate('sam-32',true)

launch_lug_arm('sam-31',false)
launch_lug_detonate('sam-31',false)

while time.time() < fire_start + lug2_off:
	# check pressures
	currFTPT = FTPT.read()
	currOTPT = OTPT.read()
	# bang bang algorithm
	if FBBopen and currFTPT > ftpt_target + upRan:
		FBB.close()
		FBBopen = False
	elif (not FBBopen) and currFTPT < ftpt_target - lowRan:
		FBB.open()
		FBBopen = True
	if OBBopen and currOTPT > otpt_target + upRan:
		OBB.close()
		OBBopen = False
	elif (not OBBopen) and currOTPT < otpt_target - lowRan:
		OBB.open()
		OBBopen = True
	wait_for(wait_timing*ms)
	
# T+3.1 turn off lug 2
launch_lug_arm('sam-32',false)
launch_lug_detonate('sam-32',false)

# only fire
while time.time() < fire_start + fire_time:
	# check pressures
	currFTPT = FTPT.read()
	currOTPT = OTPT.read()
	currPRPT = PRPT.read()
	# switch pressure check
	if FSWVclose and currPRPT < fswitch_target:
		FSWV.open()
		FSWVclose = False
	if OSWVclose and currPRPT < oswitch_target:
		OSWV.open()
		OSWVclose = False
	# BB algo
	if FBBopen and currFTPT > ftpt_target + upRan:
		FBB.close()
		FBBopen = False
	elif (not FBBopen) and currFTPT < ftpt_target - lowRan:
		FBB.open()
		FBBopen = True
	if OBBopen and currOTPT > otpt_target + upRan:
		OBB.close()
		OBBopen = False
	elif (not OBBopen) and currOTPT < otpt_target - lowRan:
		OBB.open()
		OBBopen = True
	wait_for(wait_timing*ms)

# T+26.2 close OMV before FMV
OMV.close()
OBB.close()

# loop for waiting for OMV to close
while time.time() < fire_start + fire_time + lox_close_wait:
	# BB algo
	if FBBopen and currFTPT > ftpt_target + upRan:
		FBB.close()
		FBBopen = False
	elif (not FBBopen) and currFTPT < ftpt_target - lowRan:
		FBB.open()
		FBBopen = True
	if OBBopen and currOTPT > otpt_target + upRan:
		OBB.close()
		OBBopen = False
	elif (not OBBopen) and currOTPT < otpt_target - lowRan:
		OBB.open()
		OBBopen = True
	wait_for(wait_timing*ms)

# T+26.3: close FMV
FMV.close()
FBB.close()

# T+40 end tank press
while time.time() < fire_start + post_fire_press:
	# BB algo
	if FBBopen and currFTPT > ftpt_target + upRan:
		FBB.close()
		FBBopen = False
	elif (not FBBopen) and currFTPT < ftpt_target - lowRan:
		FBB.open()
		FBBopen = True
	if OBBopen and currOTPT > otpt_target + upRan:
		OBB.close()
		OBBopen = False
	elif (not OBBopen) and currOTPT < otpt_target - lowRan:
		OBB.open()
		OBBopen = True
	wait_for(wait_timing*ms)

# T+55 fuel tank purge
while time.time() < fire_start + fuel_purge_time:
	wait_for(wait_timing*ms)
FMV.open()

# T+65 lox tank purge
while time.time() < fire_start + lox_purge_time:
	wait_for(wait_timing*ms)
OMV.open()

# T+75 open tank vents
while time.time() < fire_start + vent_open_time:
	wait_for(wait_timing*ms)
FVNT.open()
OVNT.open()

# T+78 open PRVNT
while time.time() < fire_start + prvnt_open_time:
	wait_for(wait_timing*ms)
PRVNT.open()

# T+80 open PNVNT
while time.time() < fire_start + pnvnt_open_time:
	wait_for(wait_timing*ms)
PNVNT.open()

print('Launch Sequence has ended')

