# ── Terminal → Platform ───────────────────────────────────────────────────────
TERMINAL_GENERAL_RESPONSE     = 0x0001
TERMINAL_HEARTBEAT            = 0x0002
TERMINAL_REGISTRATION         = 0x0100
TERMINAL_UNREGISTRATION       = 0x0003
QUERY_SERVER_TIME             = 0x0004
TERMINAL_AUTHENTICATION       = 0x0102
LOCATION_INFO_REPORT          = 0x0200
QUERY_TERMINAL_PARAMS_RESP    = 0x0104
QUERY_AREA_ROUTE_DATA_RESP    = 0x0608

# ── Platform → Terminal ───────────────────────────────────────────────────────
PLATFORM_GENERAL_RESPONSE     = 0x8001
TERMINAL_REGISTRATION_RESP    = 0x8100
QUERY_SERVER_TIME_RESP        = 0x8004
TERMINAL_CONTROL              = 0x8105
SET_TERMINAL_PARAMS           = 0x8103
QUERY_TERMINAL_PARAMS         = 0x8106
SET_CIRCULAR_AREA             = 0x8600
DELETE_CIRCULAR_AREA          = 0x8601
SET_RECTANGULAR_AREA          = 0x8602
DELETE_RECTANGULAR_AREA       = 0x8603
SET_POLYGON_AREA              = 0x8604
DELETE_POLYGON_AREA           = 0x8605
SET_ROUTE                     = 0x8606
DELETE_ROUTE                  = 0x8607
QUERY_AREA_ROUTE_DATA         = 0x8608

# ── Custom Control Command Words (0x8105) ─────────────────────────────────────
CMD_VEHICLE_POWER_ON          = 100
CMD_VEHICLE_POWER_OFF         = 101
CMD_START_ALARM               = 102
CMD_STOP_ALARM                = 103

# ── Custom Parameter IDs (0x8103 / 0x8106) ───────────────────────────────────
PARAM_ECU_IGNITION_PROHIBITION = 0xFF01
PARAM_GEOFENCE_SWITCH          = 0xFF02

# ── Registration response results ────────────────────────────────────────────
REG_OK                        = 0x00
REG_VEHICLE_ALREADY_REGISTERED = 0x01
REG_NO_SUCH_VEHICLE           = 0x02
REG_TERMINAL_ALREADY_REGISTERED = 0x03
REG_NO_SUCH_TERMINAL          = 0x04

# ── General response results ──────────────────────────────────────────────────
RESULT_OK                     = 0x00
RESULT_FAIL                   = 0x01
RESULT_MSG_ERROR              = 0x02
RESULT_UNSUPPORTED            = 0x03
RESULT_ALARM_ACK              = 0x04
