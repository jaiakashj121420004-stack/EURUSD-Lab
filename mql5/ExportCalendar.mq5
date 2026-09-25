//+------------------------------------------------------------------+
//| ExportCalendar.mq5                                                |
//| ROADMAP Phase 4 / SESSIONS_AND_CONTEXT.md S4.                     |
//|                                                                    |
//| READ-ONLY script. Dumps MT5's economic-calendar history to a CSV  |
//| so nylab (Python) can attach news to session data. Does NOT place |
//| or touch trades -- it only reads CalendarValueHistory().          |
//|                                                                    |
//| How to run (see README.md "Phase 4 -- economic calendar" for the  |
//| full step-by-step):                                                |
//|   1. Open MetaEditor (F4 in MT5), File > Open > this file.        |
//|   2. Compile (F7). Fix nothing -- it should compile clean.        |
//|   3. In MT5, drag the compiled script from Navigator > Scripts    |
//|      onto ANY chart (symbol/timeframe don't matter).              |
//|   4. Set inputs in the dialog that pops up (defaults are fine).   |
//|   5. Check the "Experts" tab for the printed output path.         |
//|                                                                    |
//| Calendar functions do NOT work inside the Strategy Tester -- this |
//| must be run on a live chart.                                       |
//+------------------------------------------------------------------+
#property copyright "EURUSD Session Research Lab"
#property script_show_inputs

input datetime DateFrom     = D'2021.01.01 00:00';   // pulled forward automatically, see OnStart()
input int      YearsBack    = 5;                     // used if DateFrom left at its default
input string   Currencies   = "USD,EUR";              // comma-separated ISO codes
input int      MinImportance = 1;                     // 0=none,1=low,2=moderate,3=high -- keep >=1

string OutputFile = "calendar_export.csv";

//+------------------------------------------------------------------+
int OnStart()
  {
   datetime from = DateFrom;
   datetime to   = TimeCurrent();
   // If the user left DateFrom at its literal default, compute "YearsBack years ago" instead --
   // avoids the input dialog silently using a stale hardcoded date.
   if(from == D'2021.01.01 00:00')
      from = to - YearsBack * 365 * 24 * 60 * 60;

   string currencies[];
   int n_cur = StringSplit(Currencies, ',', currencies);
   if(n_cur <= 0)
     {
      Print("ExportCalendar: no currencies parsed from input '", Currencies, "'");
      return INIT_FAILED;
     }

   int handle = FileOpen(OutputFile, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(handle == INVALID_HANDLE)
     {
      Print("ExportCalendar: could not open ", OutputFile, " for writing, error ", GetLastError());
      return INIT_FAILED;
     }

   FileWrite(handle, "time_server", "currency", "event_id", "event_name", "importance",
             "actual", "forecast", "previous", "revised_previous", "unit", "multiplier");

   int total_written = 0;
   datetime earliest_found = to;

   for(int c = 0; c < n_cur; c++)
     {
      string cur = currencies[c];
      StringTrimLeft(cur);
      StringTrimRight(cur);
      if(StringLen(cur) == 0)
         continue;

      // Chunk by calendar year -- CalendarValueHistory can choke on huge ranges for some
      // brokers' calendar databases, and this also lets us report progress per year.
      datetime chunk_from = from;
      while(chunk_from < to)
        {
         datetime chunk_to = chunk_from + 366 * 24 * 60 * 60;
         if(chunk_to > to)
            chunk_to = to;

         MqlCalendarValue values[];
         int got = CalendarValueHistory(values, chunk_from, chunk_to, NULL, cur);
         if(got < 0)
           {
            Print("ExportCalendar: CalendarValueHistory failed for ", cur, " [",
                  TimeToString(chunk_from), " - ", TimeToString(chunk_to), "], error ", GetLastError());
           }
         else
           {
            for(int i = 0; i < got; i++)
              {
               MqlCalendarEvent ev;
               MqlCalendarCountry country;
               if(!CalendarEventById(values[i].event_id, ev))
                  continue;
               if((int)ev.importance < MinImportance)
                  continue;
               if(!CalendarCountryById(ev.country_id, country))
                  continue;

               if(values[i].time < earliest_found)
                  earliest_found = values[i].time;

               string actual   = (values[i].actual_value   == LONG_MIN) ? "" : DoubleToString(values[i].actual_value   / 1000000.0, 6);
               string forecast = (values[i].forecast_value == LONG_MIN) ? "" : DoubleToString(values[i].forecast_value / 1000000.0, 6);
               string prev     = (values[i].prev_value     == LONG_MIN) ? "" : DoubleToString(values[i].prev_value     / 1000000.0, 6);
               string revprev  = (values[i].revised_prev_value == LONG_MIN) ? "" : DoubleToString(values[i].revised_prev_value / 1000000.0, 6);

               FileWrite(handle, TimeToString(values[i].time, TIME_DATE | TIME_SECONDS),
                         country.currency, (long)values[i].event_id, ev.name, (int)ev.importance,
                         actual, forecast, prev, revprev, (int)ev.unit, (int)ev.multiplier);
               total_written++;
              }
           }

         chunk_from = chunk_to;
        }
     }

   FileClose(handle);
   Print("ExportCalendar: wrote ", total_written, " rows to ", OutputFile,
         " (find it under MQL5/Files/ in your MT5 data folder -- File > Open Data Folder).");
   Print("ExportCalendar: earliest event found: ", TimeToString(earliest_found, TIME_DATE),
         " -- if this is later than you expected, that's the depth of MetaQuotes' own calendar "
         "database for this broker, not a bug in this script.");
   return INIT_SUCCEEDED;
  }
//+------------------------------------------------------------------+
