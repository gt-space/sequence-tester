// Synthetic producer/decoder only. Production common source is unmodified.
use common::comm::{VehicleState, Measurement, CompositeValveState, ValveState, sam::Unit, flight::SequenceDomainCommand};
use mmap_sync::synchronizer::Synchronizer;
use std::{io::Read, time::Duration};
fn main() {
    // Fail closed even if this helper is accidentally invoked outside its runner.
    let host: serde_json::Value=serde_json::from_str(&std::env::var("AUDIT_HOST_NAMESPACES").expect("isolation metadata required")).unwrap();
    for name in ["mnt","ipc","net","pid"] {
        let current=std::fs::read_link(format!("/proc/self/ns/{name}")).unwrap();
        assert_ne!(current.to_str().unwrap(),host[name].as_str().unwrap(),"namespace isolation required");
    }
    assert!(!std::path::Path::new("/home").exists());
    let args: Vec<String> = std::env::args().collect();
    if args[1] == "decode" {
        let mut bytes=Vec::new(); std::io::stdin().read_to_end(&mut bytes).unwrap();
        let command: SequenceDomainCommand=postcard::from_bytes(&bytes).unwrap();
        println!("{}",serde_json::to_string(&command).unwrap()); return;
    }
    let mut state=VehicleState::default();
    let value: f64=args[1].parse().unwrap();
    let unit=match args[2].as_str() {"psi"=>Unit::Psi,"V"=>Unit::Volts,"A"=>Unit::Amps,"K"=>Unit::Kelvin,"lbf"=>Unit::Pounds,_=>Unit::Unknown};
    state.sensor_readings.insert("FTPT".into(),Measurement{value,unit});
    state.valve_states.insert("valve".into(),CompositeValveState{commanded:ValveState::Closed,actual:ValveState::Open});
    let mut sync=Synchronizer::new(std::ffi::OsStr::new("/dev/shm/fc_vehicle_state"));
    sync.write(&state,Duration::from_millis(100)).unwrap();
}
