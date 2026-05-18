============================================================================

SCRIPT: DMR Digital Contacts CSV Generator

AUTHOR: Tyler L, callsign KR4DSO

PURPOSE: Use Python to automate the retrieval, merging, and formatting of DMR contact data from RadioID.net and the FCC Universal Licensing System (ULS) for import into your radio's CPS software.

============================================================================

Intro:

I looked around and could not find a script, service, or program that did what I was looking for. I can't stand having a contacts list with only first names, especially when I'm grabbing a list of people all across the US (there are so many Johns). I also noticed when comparing callsigns against the ULS database, the city listed in RadioID.net wasn't up to date. So I set out to figure out a script that could take the user list from RadioID.net and validate it against the FCC ULS database to give me up-to-date city names, and give me the last name in the "name" field for my radio (currently using the DM-32UV). With the help of Google's Gemini Pro, I got a working script and ultimately was able to wrap it up into a click-to-run application with options for your specific radio and output path.

============================================================================

This script is divided into 4 parts:

PART 1: Fetch and Filter RadioID.net Data

Reaches out to RadioID.net and pulls the most recent copy of 'users.csv' and filters it to only show contacts with the Country field of United States and exports to 'US_RADIOID.csv'.

PART 2: Download and Parse FCC ULS Bulk Data

Downloads the weekly 'l_amat.zip' from the FCC's ULS database. This file is updated weekly on Sunday mornings.

PART 3: Merge RadioID and FCC Data Locally

Takes the CSVs from RadioID.net and the FCC ULS database and matches each callsign to the first and last name, city, and state of each entry in the RadioID CSV and merges them into a separate 'RADIOID_FCC_MERGED.csv'.

PART 4: Format Data for your radio-specific CPS Import

Imports the data from the 'RADIOID_FCC_MERGED.csv' and formats to what your CPS is looking for and exports to 'DMR_CONTACTS_(your radio model).csv'.

============================================================================

73
