# tank pre press sequence
import time
print('Pre Press Sequence has begun')

# define pressure variables
ftpt_target = 416*psi # psia, target fuel tank pressure
otpt_target = 357*psi # psia, target lox tank pressure
upRan = 2*psi # psi, upper range bound for bang bang algorithm
lowRan = 3*psi # psi, lower range bound for bang bang algorithm

# time variables
press_time = 20 # s, sequence duration
wait_timing = 5 # ms

# confirm switch closed
FSWV.close()
OSWV.close()
wait_for(wait_timing*ms)

# initialize valve state variables
FBB.close()
FBBopen = False # hardcoded for consistency
OBB.close()
OBBopen = False # hardcoded due to feedback issues on sam-21

start_time = time.time() # s, current time

# press tanks with bang bang algorithm
while time.time() < start_time + press_time:
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

OBB.close()
FBB.close()

print('Pre Press Sequence has ended')
