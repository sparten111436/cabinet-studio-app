(* ============================================================
   Cabinet Studio — cut/paste stub
   Platform: Allen-Bradley Logix structured text
   Not downloaded to a controller.

   Replace the symbols below with controller tags. Copy the
   address from each device's PLC I/O field in Cabinet Studio.

   Tag            Direction    Address placeholder
   START_PB       Input        Local:1:I.Data.0
   STOP_PB        Input        Local:1:I.Data.1
   ESTOP_OK       Input        Local:1:I.Data.2
   RUN_CMD        Output       Local:2:O.Data.0
   FAULT_LAMP     Output       Local:2:O.Data.1
   ============================================================ *)

RunSeal := (StartPB OR RunSeal) AND NOT StopPB AND EStopOK AND NOT Fault;
RunCmd := RunSeal;
FaultLamp := Fault;
