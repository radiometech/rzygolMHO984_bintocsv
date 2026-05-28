# MHO984 .bin → CSV / Plot

Python GUI tool for converting Micsig MHO984 oscilloscope binary recordings to CSV files and waveform plots.

## Features

- Automatic detection of RG03 binary format (sample rate, channel count, data offset)
- Multi-channel export — all channels in a single CSV file (`Time, CH1, CH2, CH3, CH4`)
- Streaming I/O — handles files larger than 1 GB without loading them into RAM
- Interactive waveform plot with zoom/pan toolbar (one subplot per channel)
- Save plot as PNG
- Configurable decimation to reduce output file size

## Requirements

```
pip install numpy matplotlib
```

Python 3.10+

## Usage

Run `main.py` — the GUI will open and auto-detect any `.bin` file in the project folder.

1. Click **Przeglądaj** to select a `.bin` file, then **Wczytaj** to parse the header
2. Check the detected parameters in the info bar (sample rate, duration, channel count)
3. Click **Pokaż wykres** to open an interactive plot window
4. Click **Eksport CSV (wszystkie kanały)** to save all channels to a single CSV file

## CSV output format

```
Time (s),CH1 (V),CH2 (V),CH3 (V),CH4 (V)
0.000000,0.001280,0.000980,0.001610,0.001570
0.000010,0.001640,0.000940,...
```

## Notes

- Tested with Micsig MHO984 (RG03 format). Other Micsig models using the same format should work.
- If channels appear swapped, toggle the **Data layout** option between `sequential` and `interleaved`.
- Use the **Decymacja** field to downsample the CSV output (e.g. `10` = every 10th sample).
