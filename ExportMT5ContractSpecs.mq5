#property script_show_inputs

input string InpOutputFile = "mt5_contract_specs.csv";

void OnStart()
  {
   int file=FileOpen(InpOutputFile,FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON,',');
   if(file==INVALID_HANDLE)
     {
      Print("Could not create contract CSV. Error: ",GetLastError());
      return;
     }

   FileWrite(file,
             "symbol",
             "point_size",
             "tick_size",
             "tick_value_per_lot",
             "point_value_per_point_per_lot",
             "points_per_ea_pip",
             "lot_step",
             "min_lot",
             "max_lot",
             "account_currency",
             "profit_currency");

   int exported=0;
   int skipped=0;
   int total=SymbolsTotal(true);
   for(int index=0;index<total;index++)
     {
      string symbol=SymbolName(index,true);
      double point_size=SymbolInfoDouble(symbol,SYMBOL_POINT);
      double tick_size=SymbolInfoDouble(symbol,SYMBOL_TRADE_TICK_SIZE);
      double tick_value=SymbolInfoDouble(symbol,SYMBOL_TRADE_TICK_VALUE);
      double lot_step=SymbolInfoDouble(symbol,SYMBOL_VOLUME_STEP);
      double min_lot=SymbolInfoDouble(symbol,SYMBOL_VOLUME_MIN);
      double max_lot=SymbolInfoDouble(symbol,SYMBOL_VOLUME_MAX);

      if(point_size<=0.0 || tick_size<=0.0 || tick_value<=0.0 ||
         lot_step<=0.0 || min_lot<=0.0 || max_lot<min_lot)
        {
         Print("Skipped ",symbol,
               ": broker did not provide valid point/tick/volume properties.");
         skipped++;
         continue;
        }

      double point_value=tick_value*point_size/tick_size;
      string account_currency=AccountInfoString(ACCOUNT_CURRENCY);
      string profit_currency=SymbolInfoString(symbol,SYMBOL_CURRENCY_PROFIT);
      FileWrite(file,
                symbol,
                DoubleToString(point_size,10),
                DoubleToString(tick_size,10),
                DoubleToString(tick_value,8),
                DoubleToString(point_value,8),
                "",
                DoubleToString(lot_step,8),
                DoubleToString(min_lot,8),
                DoubleToString(max_lot,8),
                account_currency,
                profit_currency);
      exported++;
     }

   FileClose(file);
   Print("Exported ",exported," symbols; skipped ",skipped," symbols.");
   Print("CSV saved under the terminal Common Files folder: ",InpOutputFile);
  }
