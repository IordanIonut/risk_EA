#property strict

#include <Trade/Trade.mqh>

input double InpDailyLossLimitCash = 450.0;
input double InpDailyStartingEquity = 0.0;
input int InpDailyResetHour = 0;
input double InpInitialAccountBalance = 0.0;
input double InpOverallLossLimitCash = 0.0;
input string InpManagedMagicNumbers = "*";
input string InpLockVariableSuffix = "MT5_RISK_GUARD_LOCKED";
input long InpGuardId = 849121;
input int InpCheckIntervalSeconds = 1;

CTrade g_trade;
string g_state_prefix;
string g_shared_lock_name;
string g_daily_baseline_key;
string g_daily_anchor_key;
string g_daily_lock_key;
string g_overall_lock_key;
datetime g_daily_anchor = 0;
double g_daily_baseline = 0.0;
bool g_daily_locked = false;
bool g_overall_locked = false;
bool g_ready = false;

string Trimmed(string value)
  {
   StringTrimLeft(value);
   StringTrimRight(value);
   return value;
  }

datetime CurrentDailyAnchor(datetime now)
  {
   MqlDateTime parts;
   TimeToStruct(now,parts);
   parts.hour=InpDailyResetHour;
   parts.min=0;
   parts.sec=0;
   datetime anchor=StructToTime(parts);
   if(now<anchor)
      anchor-=86400;
   return anchor;
  }

bool IsManagedMagic(long magic)
  {
   string configured=Trimmed(InpManagedMagicNumbers);
   if(configured=="" || configured=="*")
      return true;

   string entries[];
   int count=StringSplit(configured,',',entries);
   for(int index=0;index<count;index++)
     {
      string entry=Trimmed(entries[index]);
      if(entry!="" && StringToInteger(entry)==magic)
         return true;
     }
   return false;
  }

bool ValidManagedMagicFilter()
  {
   string configured=Trimmed(InpManagedMagicNumbers);
   if(configured=="" || configured=="*")
      return true;

   string entries[];
   int count=StringSplit(configured,',',entries);
   if(count<=0)
      return false;
   for(int index=0;index<count;index++)
     {
      string entry=Trimmed(entries[index]);
      if(entry=="")
         return false;
      for(int character=0;character<StringLen(entry);character++)
        {
         ushort value=StringGetCharacter(entry,character);
         if(value<'0' || value>'9')
            return false;
        }
     }
   return true;
  }

void StoreDailyState()
  {
   if(GlobalVariableSet(g_daily_baseline_key,g_daily_baseline)==0)
      Print("Risk guard could not persist daily baseline. Error: ",GetLastError());
   if(GlobalVariableSet(g_daily_anchor_key,(double)g_daily_anchor)==0)
      Print("Risk guard could not persist daily reset time. Error: ",GetLastError());
   if(GlobalVariableSet(g_daily_lock_key,g_daily_locked ? 1.0 : 0.0)==0)
      Print("Risk guard could not persist daily lock. Error: ",GetLastError());
   GlobalVariablesFlush();
  }

void UpdateSharedLock()
  {
   double locked=(g_daily_locked || g_overall_locked) ? 1.0 : 0.0;
   if(GlobalVariableSet(g_shared_lock_name,locked)==0)
      Print("Risk guard could not publish its lock variable. Error: ",GetLastError());
   if(GlobalVariableSet(g_overall_lock_key,g_overall_locked ? 1.0 : 0.0)==0)
      Print("Risk guard could not persist overall lock. Error: ",GetLastError());
   GlobalVariablesFlush();
  }

void CloseManagedExposure()
  {
   for(int index=PositionsTotal()-1;index>=0;index--)
     {
      ulong ticket=PositionGetTicket(index);
      if(ticket==0)
         continue;
      long magic=PositionGetInteger(POSITION_MAGIC);
      if(!IsManagedMagic(magic))
         continue;
      if(!g_trade.PositionClose(ticket))
         Print("Could not close position ",ticket,": ",
               g_trade.ResultRetcode()," ",g_trade.ResultRetcodeDescription());
     }

   for(int index=OrdersTotal()-1;index>=0;index--)
     {
      ulong ticket=OrderGetTicket(index);
      if(ticket==0)
         continue;
      long magic=OrderGetInteger(ORDER_MAGIC);
      if(!IsManagedMagic(magic))
         continue;
      if(!g_trade.OrderDelete(ticket))
         Print("Could not delete pending order ",ticket,": ",
               g_trade.ResultRetcode()," ",g_trade.ResultRetcodeDescription());
     }
  }

int OnInit()
  {
   if(!MathIsValidNumber(InpDailyLossLimitCash) ||
      !MathIsValidNumber(InpDailyStartingEquity) ||
      !MathIsValidNumber(InpInitialAccountBalance) ||
      !MathIsValidNumber(InpOverallLossLimitCash) ||
      InpDailyLossLimitCash<=0.0 ||
      InpDailyStartingEquity<0.0 ||
      InpDailyResetHour<0 || InpDailyResetHour>23 ||
      InpInitialAccountBalance<0.0 ||
      InpOverallLossLimitCash<0.0 ||
      (InpOverallLossLimitCash>0.0 && InpInitialAccountBalance<=0.0) ||
      InpCheckIntervalSeconds<1 ||
      InpGuardId<=0 ||
      Trimmed(InpLockVariableSuffix)=="" ||
      StringLen(Trimmed(InpLockVariableSuffix))>40 ||
      !ValidManagedMagicFilter())
     {
      Print("Invalid risk-guard inputs. Daily limit and check interval must be positive; ",
            "overall loss needs a positive initial account balance.");
      return INIT_PARAMETERS_INCORRECT;
     }

   long login=AccountInfoInteger(ACCOUNT_LOGIN);
   string account_id=IntegerToString(login);
   g_state_prefix="RiskGuard."+account_id+"."+IntegerToString(InpGuardId);
   g_shared_lock_name=Trimmed(InpLockVariableSuffix)+"_"+account_id;
   g_daily_baseline_key=g_state_prefix+".daily_baseline";
   g_daily_anchor_key=g_state_prefix+".daily_anchor";
   g_daily_lock_key=g_state_prefix+".daily_locked";
   g_overall_lock_key=g_state_prefix+".overall_locked";
   if(GlobalVariableSet(g_shared_lock_name,1.0)==0)
     {
      Print("Risk guard could not create its shared lock variable. Error: ",GetLastError());
      return INIT_FAILED;
     }
   GlobalVariablesFlush();

   datetime now=TimeTradeServer();
   if(now<=0)
     {
      Print("Server time is unavailable. Risk guard will not start.");
      return INIT_FAILED;
     }
   datetime current_anchor=CurrentDailyAnchor(now);
   if(GlobalVariableCheck(g_daily_baseline_key) &&
      GlobalVariableCheck(g_daily_anchor_key))
     {
      g_daily_baseline=GlobalVariableGet(g_daily_baseline_key);
      g_daily_anchor=(datetime)GlobalVariableGet(g_daily_anchor_key);
      g_daily_locked=GlobalVariableCheck(g_daily_lock_key) &&
                     GlobalVariableGet(g_daily_lock_key)>0.5;
      if(g_daily_locked && InpDailyStartingEquity>0.0 &&
         current_anchor==g_daily_anchor)
        {
         g_daily_baseline=InpDailyStartingEquity;
         g_daily_locked=false;
         StoreDailyState();
         Print("Daily lock manually reset using InpDailyStartingEquity.");
        }
      if(current_anchor>g_daily_anchor)
        {
         int seconds_after_reset=(int)(now-current_anchor);
         int reset_tolerance=MathMax(10,InpCheckIntervalSeconds*2);
         if(seconds_after_reset<=reset_tolerance)
           {
            g_daily_anchor=current_anchor;
            g_daily_baseline=AccountInfoDouble(ACCOUNT_EQUITY);
            g_daily_locked=false;
            StoreDailyState();
           }
         else if(InpDailyStartingEquity>0.0)
           {
            g_daily_anchor=current_anchor;
            g_daily_baseline=InpDailyStartingEquity;
            g_daily_locked=false;
            StoreDailyState();
            Print("Daily baseline reset from the manually supplied input after a missed reset.");
           }
         else
           {
            g_daily_anchor=current_anchor;
            g_daily_locked=true;
            StoreDailyState();
            Print("Risk guard missed the daily reset while offline. It is locked closed; ",
                  "set InpDailyStartingEquity from the prop dashboard, then re-attach.");
           }
        }
     }
   else
     {
      if(InpDailyStartingEquity<=0.0)
        {
         Print("First installation needs InpDailyStartingEquity from the prop dashboard. ",
               "The guard will not guess the day's starting equity.");
         return INIT_PARAMETERS_INCORRECT;
        }
      g_daily_anchor=current_anchor;
      g_daily_baseline=InpDailyStartingEquity;
      g_daily_locked=false;
      StoreDailyState();
     }

   g_overall_locked=GlobalVariableCheck(g_overall_lock_key) &&
                    GlobalVariableGet(g_overall_lock_key)>0.5;
   double initial_equity=AccountInfoDouble(ACCOUNT_EQUITY);
   if(g_daily_baseline-initial_equity>=InpDailyLossLimitCash)
      g_daily_locked=true;
   if(InpOverallLossLimitCash>0.0 &&
      InpInitialAccountBalance-initial_equity>=InpOverallLossLimitCash)
      g_overall_locked=true;
   if(g_daily_locked)
      StoreDailyState();
   g_ready=true;
   UpdateSharedLock();
   if(!EventSetTimer(InpCheckIntervalSeconds))
     {
      g_daily_locked=true;
      StoreDailyState();
      UpdateSharedLock();
      g_ready=false;
      Print("Risk guard could not start its timer. Error: ",GetLastError());
      return INIT_FAILED;
     }
   if(g_daily_locked || g_overall_locked)
     {
      Print("Configured equity loss limit is already exceeded at initialization.");
      CloseManagedExposure();
     }
   Print("Risk guard active. Shared lock variable: ",g_shared_lock_name,
         "; use the same account-wide name in cooperating EAs.");
   Print("Managed magic filter: ",
         (Trimmed(InpManagedMagicNumbers)=="" ? "*" : InpManagedMagicNumbers),
         ". A lock in this guard cannot stop another EA from reopening trades.");
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   if(g_shared_lock_name!="")
     {
      if(GlobalVariableSet(g_shared_lock_name,1.0)==0)
         Print("Risk guard could not leave the shared lock active. Error: ",GetLastError());
      GlobalVariablesFlush();
     }
   g_ready=false;
  }

void OnTimer()
  {
   if(!g_ready)
      return;

   datetime now=TimeTradeServer();
   if(now<=0)
     {
      g_daily_locked=true;
      StoreDailyState();
      UpdateSharedLock();
      CloseManagedExposure();
      Print("Server time is unavailable. Risk guard is locked closed.");
      return;
     }
   datetime current_anchor=CurrentDailyAnchor(now);
   if(current_anchor>g_daily_anchor)
     {
      int seconds_after_reset=(int)(now-current_anchor);
      int reset_tolerance=MathMax(10,InpCheckIntervalSeconds*2);
      g_daily_anchor=current_anchor;
      if(seconds_after_reset<=reset_tolerance)
        {
         g_daily_baseline=AccountInfoDouble(ACCOUNT_EQUITY);
         g_daily_locked=false;
         Print("Daily risk baseline reset to ",DoubleToString(g_daily_baseline,2),
               " at server reset time.");
        }
      else if(InpDailyStartingEquity>0.0)
        {
         g_daily_baseline=InpDailyStartingEquity;
         g_daily_locked=false;
         Print("Daily risk baseline reloaded from InpDailyStartingEquity after a missed reset.");
        }
      else
        {
         g_daily_locked=true;
         Print("Daily reset was missed; the guard is locked until a manual baseline is supplied.");
        }
      StoreDailyState();
      UpdateSharedLock();
     }

   double equity=AccountInfoDouble(ACCOUNT_EQUITY);
   if(g_daily_baseline-equity>=InpDailyLossLimitCash && !g_daily_locked)
     {
      g_daily_locked=true;
      StoreDailyState();
      UpdateSharedLock();
      Print("DAILY EQUITY LOSS LIMIT reached. Closing managed positions and pending orders.");
     }
   if(InpOverallLossLimitCash>0.0 &&
      InpInitialAccountBalance-equity>=InpOverallLossLimitCash &&
      !g_overall_locked)
     {
      g_overall_locked=true;
      UpdateSharedLock();
      Print("OVERALL EQUITY LOSS LIMIT reached. Closing managed positions and pending orders.");
     }

   if(g_daily_locked || g_overall_locked)
      CloseManagedExposure();
  }

void OnTick()
  {
  }
