#property script_show_inputs

input string InpSymbol = "";
input ENUM_TIMEFRAMES InpTimeframe = PERIOD_D1;
input int InpBarsToExport = 2000;
input string InpOutputFile = "mt5_history.csv";
input bool InpIncludeTickSpreadStats = true;

void GetTickSpreadStats(const string symbol,
                        const MqlRates &bar,
                        const datetime end_time,
                        const double point_size,
                        double &max_spread_points,
                        double &average_spread_points,
                        long &spread_sample_count)
  {
   max_spread_points=0.0;
   average_spread_points=0.0;
   spread_sample_count=0;
   if(point_size<=0.0 || end_time<=bar.time)
      return;

   MqlTick ticks[];
   ulong from_msc=(ulong)bar.time*1000;
   ulong to_msc=(ulong)end_time*1000-1;
   int copied=CopyTicksRange(symbol,ticks,COPY_TICKS_INFO,from_msc,to_msc);
   if(copied<0)
     {
      Print("Could not read tick spread data for ",symbol," at ",
            TimeToString(bar.time,TIME_DATE|TIME_MINUTES),
            ". Error: ",GetLastError());
      return;
     }
   if(copied==0)
      return;

   double spread_sum=0.0;
   for(int index=0;index<copied;index++)
     {
      if(ticks[index].bid<=0.0 || ticks[index].ask<ticks[index].bid)
         continue;
      double spread=(ticks[index].ask-ticks[index].bid)/point_size;
      if(spread<0.0)
         continue;
      spread_sum+=spread;
      if(spread>max_spread_points)
         max_spread_points=spread;
      spread_sample_count++;
     }

   if(spread_sample_count>0)
      average_spread_points=spread_sum/(double)spread_sample_count;
  }

void OnStart()
  {
   string symbol=InpSymbol;
   if(symbol=="")
      symbol=_Symbol;

   if(InpBarsToExport<20)
     {
      Print("InpBarsToExport must be at least 20.");
      return;
     }
   if(!SymbolSelect(symbol,true))
     {
      Print("Could not select symbol ",symbol,". Error: ",GetLastError());
      return;
     }

   MqlRates rates[];
   ArraySetAsSeries(rates,false);
   int copied=CopyRates(symbol,InpTimeframe,0,InpBarsToExport,rates);
   if(copied<20)
     {
      Print("At least 20 history bars are required; copied ",copied,
            ". Check that MT5 has downloaded the requested history.");
      return;
     }

   int file=FileOpen(InpOutputFile,FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',');
   if(file==INVALID_HANDLE)
     {
      Print("Could not create history CSV. Error: ",GetLastError());
      return;
     }

   FileWrite(file,
             "symbol",
             "timeframe",
             "date",
             "time",
             "open",
             "high",
             "low",
             "close",
             "tick_volume",
             "spread",
             "spread_max_points",
             "spread_avg_points",
             "spread_sample_count",
             "real_volume");

   int digits=(int)SymbolInfoInteger(symbol,SYMBOL_DIGITS);
   double point_size=SymbolInfoDouble(symbol,SYMBOL_POINT);
   long bars_with_tick_spread=0;
   for(int index=0;index<copied;index++)
     {
      datetime bar_end;
      if(index+1<copied)
         bar_end=rates[index+1].time;
      else
        {
         int period_seconds=PeriodSeconds(InpTimeframe);
         bar_end=period_seconds>0
                 ? rates[index].time+period_seconds
                 : TimeCurrent();
         if(bar_end>TimeCurrent())
            bar_end=TimeCurrent();
        }

      double max_spread_points=0.0;
      double average_spread_points=0.0;
      long spread_sample_count=0;
      if(InpIncludeTickSpreadStats)
        {
         GetTickSpreadStats(symbol,
                            rates[index],
                            bar_end,
                            point_size,
                            max_spread_points,
                            average_spread_points,
                            spread_sample_count);
        }
      if(spread_sample_count>0)
         bars_with_tick_spread++;
      else
         max_spread_points=(double)rates[index].spread;

      FileWrite(file,
                symbol,
                EnumToString(InpTimeframe),
                TimeToString(rates[index].time,TIME_DATE),
                TimeToString(rates[index].time,TIME_MINUTES|TIME_SECONDS),
                DoubleToString(rates[index].open,digits),
                DoubleToString(rates[index].high,digits),
                DoubleToString(rates[index].low,digits),
                DoubleToString(rates[index].close,digits),
                (long)rates[index].tick_volume,
                rates[index].spread,
                DoubleToString(max_spread_points,4),
                spread_sample_count>0
                   ? DoubleToString(average_spread_points,4)
                   : "",
                spread_sample_count,
                (long)rates[index].real_volume);
     }

   FileClose(file);
   Print("Exported ",copied," bars for ",symbol," (",
         EnumToString(InpTimeframe),").");
   Print("Bars with tick-derived spread samples: ",
         bars_with_tick_spread," / ",copied,
         ". Bars without tick data use the bar's spread value as fallback.");
   Print("CSV saved in the terminal Common Files folder: ",InpOutputFile);
  }
