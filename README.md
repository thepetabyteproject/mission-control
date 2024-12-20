# mission-control

Mission Control is a graphic user interface designed to make it easy to interact with a database and launch jobs to process data. It was designed for the Petabyte Project (TPP), allowing users to query the TPP database, find surveys referenced within that need processing, and run our custom pipeline on the data.

The code is written in Python, using tkinter. In theory, it can be adapted for projects beyond TPP; this would require some minor rewrites of the code to 1) replace interactions with the TPP database with however the new project's data is organized, and 2) remove the TPP launcher and replace it with a call to the desired processing script.

The only non-standard packages required are Astropy and [the TPP package](https://github.com/thepetabyteproject/tpp) itself; the latter is needed to access the TPP database and run the TPP pipeline. If Mission Control is ever used for other projects, the TPP package *should* become unnecessary, and the code can be adapted as needed.
