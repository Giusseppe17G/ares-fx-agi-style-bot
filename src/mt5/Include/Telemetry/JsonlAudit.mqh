#ifndef AGI_NATIVE_JSONL_AUDIT_MQH
#define AGI_NATIVE_JSONL_AUDIT_MQH
#include <Contracts/MarketSnapshot.mqh>

string NativeJsonString(const string value)
  {
   string escaped="\"";
   for(int i=0;i<StringLen(value);i++)
     {
      ushort c=StringGetCharacter(value,i);
      if(c==34) escaped+="\\\"";
      else if(c==92) escaped+="\\\\";
      else if(c<32) escaped+=StringFormat("\\u%04x",c);
      else escaped+=StringSubstr(value,i,1);
     }
   return escaped+"\"";
  }

string NativeUtcJson(const datetime instant)
  {
   if(instant<=0) return "null";
   MqlDateTime dt={};
   if(!TimeToStruct(instant,dt)) return "null";
   return StringFormat("\"%04d-%02d-%02dT%02d:%02d:%02dZ\"",dt.year,dt.mon,dt.day,dt.hour,dt.min,dt.sec);
  }

string NativeSnapshotJson(const MarketSnapshot &s)
  {
   return "{\"symbol\":"+NativeJsonString(s.symbol)+",\"timeframe\":"+NativeJsonString(s.timeframe)+
      ",\"timestamp_utc\":"+NativeUtcJson(s.timestamp_utc)+
      ",\"timestamp_utc_msc\":"+IntegerToString(s.timestamp_utc_msc)+
      ",\"source_tick_server_msc\":"+IntegerToString(s.source_tick_server_msc)+
      ",\"observed_at_utc\":"+NativeUtcJson(s.observed_at_utc)+
      ",\"bid\":"+DoubleToString(s.bid,16)+",\"ask\":"+DoubleToString(s.ask,16)+
      ",\"spread_points\":"+DoubleToString(s.spread_points,10)+
      ",\"digits\":"+IntegerToString(s.digits)+",\"point\":"+DoubleToString(s.point,16)+
      ",\"tick_value\":"+DoubleToString(s.tick_value,16)+",\"tick_size\":"+DoubleToString(s.tick_size,16)+
      ",\"volume_min\":"+DoubleToString(s.volume_min,16)+",\"volume_max\":"+DoubleToString(s.volume_max,16)+
      ",\"volume_step\":"+DoubleToString(s.volume_step,16)+
      ",\"stops_level_points\":"+IntegerToString(s.stops_level_points)+
      ",\"freeze_level_points\":"+IntegerToString(s.freeze_level_points)+"}";
  }

class NativeJsonlAudit
  {
private:
   int m_handle;
   long m_sequence;
   ulong m_bytes;
   string m_run_id;
   bool m_healthy;
   bool m_demo_verified;
public:
   NativeJsonlAudit(void)
     { m_handle=INVALID_HANDLE; m_sequence=0; m_bytes=0; m_healthy=false; m_demo_verified=false; }
   bool Open(void)
     {
      if(m_handle!=INVALID_HANDLE) return false;
      string seed="native_"+IntegerToString((long)GetTickCount64())+"_"+IntegerToString((long)GetMicrosecondCount());
      for(int attempt=0;attempt<100;attempt++)
        {
         m_run_id=seed+"_"+IntegerToString(attempt);
         string relative_path="AGI_STYLE_FOREX_BOT_MT5\\native_observation\\"+m_run_id+".jsonl";
         if(FileIsExist(relative_path)) continue;
         // Never use common folders, supplied paths, network pipes or sharing.
         ResetLastError();
         m_handle=FileOpen(relative_path,FILE_READ|FILE_WRITE|FILE_BIN);
         if(m_handle==INVALID_HANDLE) return false;
         if(FileSize(m_handle)!=0 || GetLastError()!=0)
           { Close(); return false; }
         m_healthy=true;
         return true;
        }
      return false;
     }
   void SetDemoVerified(const bool verified=true) { m_demo_verified=verified; }
   bool Healthy(void) { return m_healthy && m_handle!=INVALID_HANDLE; }
   bool Append(const datetime now_utc,const string event_type,const string severity,
               const string symbol,const string reason,const string payload="{}")
     {
      if(!Healthy()) return false;
      m_sequence++;
      string identity=m_run_id+":"+IntegerToString(m_sequence);
      string line="{\"schema_version\":\"native_observation_event_v1\",\"scope\":\"NATIVE_OBSERVATION_ONLY\","+
         "\"event_id\":"+NativeJsonString(identity)+",\"idempotency_key\":"+NativeJsonString(identity)+
         ",\"correlation_id\":"+NativeJsonString(m_run_id)+",\"run_id\":"+NativeJsonString(m_run_id)+
         ",\"sequence_number\":"+IntegerToString(m_sequence)+",\"timestamp_utc\":"+NativeUtcJson(now_utc)+
         ",\"environment\":"+(m_demo_verified ? "\"DEMO\"" : "null")+
         ",\"severity\":"+NativeJsonString(severity)+",\"module\":\"native_observer\",\"event_type\":"+
         NativeJsonString(event_type)+",\"symbol\":"+NativeJsonString(symbol)+",\"reason\":"+NativeJsonString(reason)+
         ",\"execution_authorized\":false,\"execution_attempted\":false,\"release_status\":\"BLOCKED\","+
         "\"clock_authenticity_verified\":false,\"payload_json\":"+payload+"}\n";
      uchar bytes[];
      int count=StringToCharArray(line,bytes,0,-1,CP_UTF8)-1;
      if(count<=0 || m_bytes+(ulong)count>50*1024*1024 || FileSize(m_handle)!=m_bytes || FileTell(m_handle)!=m_bytes)
        { m_healthy=false; return false; }
      ResetLastError();
      uint written=FileWriteArray(m_handle,bytes,0,count);
      if(written!=(uint)count || GetLastError()!=0)
        { m_healthy=false; return false; }
      ResetLastError();
      FileFlush(m_handle);
      if(GetLastError()!=0 || FileSize(m_handle)!=m_bytes+(ulong)count || !FileSeek(m_handle,(long)m_bytes,SEEK_SET))
        { m_healthy=false; return false; }
      uchar verified[];
      ArrayResize(verified,count);
      ResetLastError();
      if(FileReadArray(m_handle,verified,0,count)!=(uint)count || GetLastError()!=0)
        { m_healthy=false; return false; }
      for(int i=0;i<count;i++)
         if(verified[i]!=bytes[i]) { m_healthy=false; return false; }
      m_bytes+=(ulong)count;
      if(!FileSeek(m_handle,0,SEEK_END) || FileTell(m_handle)!=m_bytes)
        { m_healthy=false; return false; }
      return true;
     }
   void Close(void)
     {
      if(m_handle!=INVALID_HANDLE) FileClose(m_handle);
      m_handle=INVALID_HANDLE;
      m_healthy=false;
     }
  };
#endif
