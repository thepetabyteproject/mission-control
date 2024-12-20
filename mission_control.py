#!/usr/bin/env python3
#
# Created 7/16/24 by Graham Doskoch. Last modfied 12/20/24.
#
# This script creates a GUI for a user to submit jobs to process pointings
# for The Petabyte Project (TPP). It uses tkinter and TPP's database
# communications infrastructure. It's built in a modular structure, with
# classes, to enable easy modifications, tweaks and customization.
#
# The main class is Launcher, which provides a window with several inputs.
# The users tweaks these inputs to select certain subsets of the data from
# a particular survey. Launcher then creates a separate window, an
# instance of the GlobalInfoWindow class, with information on all of the
# selected pointings.
#
# All of the other classes contained in this code are used to group together
# tkinter widgets within a window, and were written for the sake of
# convenience.

# TODO
# - Nothing? Somehow?

import matplotlib.pyplot as plt
import numpy as np
import random
import requests
import shlex
import subprocess
import sys
import tkinter as tk

from astropy import units as u
from astropy.coordinates import SkyCoord
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from tkinter import scrolledtext

from tpp.data import db as dbconfig
from tpp.infrastructure import database as db

tpp_url = f"http://{dbconfig['tpp-db']['ip']}:{dbconfig['tpp-db']['port']}/"
headers_file = {"Authorization": f"Bearer {dbconfig['tpp-db']['token']}"}

# Note: Can any of the below be folded into main()? I don't think so, but it's
# worth looking into.
#
# Grabs all parent surveys from the database and creates a list of (child)
# surveys for each one
response = requests.get("{}survey".format(tpp_url), headers=headers_file)
survey_info = response.json()

surveys = {}
parent_surveys = []

for inf in survey_info:
    s = inf["survey"]
    p = inf["parent_survey"]
    
    if p not in parent_surveys:
        parent_surveys.append(p)
        surveys[p] = [s]
    else:
        if s not in surveys[p]:
            surveys[p].append(s)
        else:
            pass
        
parent_surveys = sorted(parent_surveys)
for p in parent_surveys:
    surveys[p] = sorted(surveys[p])

class Launcher(tk.Frame):
    """
    
    This is the class behind the first window the user sees. It contains
    widgets that select pointings from a chosen survey based on various
    criteria, including frequency, MJD, and sky location.
    
    Input:
        parent: the parent object in which to place the window
    
    """
    def __init__(self, parent):
        tk.Frame.__init__(self, parent)

        self.parent = parent

        # Frame containing all other widgets within Launcher
        self.frame = tk.Frame(self.parent)
        self.frame.grid(row=0, column=0)

        # First, there are dropdown menus with which the user
        # selects a parent survey and a survey within it.
        self.surveys_choice_frame = tk.Frame(self.frame)
        self.surveys_choice_frame.grid(row=0, column=0, sticky="nsew", pady=2)
        
        # Populated with placeholder surveys
        self.parent_survey_block = DropDownBlock(
            self.surveys_choice_frame, "Parent survey", parent_surveys)
        self.parent_survey_block.dropdown_value.trace("w", self.check_parent_survey_choice)
        self.parent_survey_block.frame.grid(row=0, column=0, sticky="nsew", padx=2)
        
        # Placeholders
        self.survey_options_dict = surveys
        # Populated with more placeholders
        self.survey_block = DropDownBlock(
            self.surveys_choice_frame, "Survey", surveys[parent_surveys[0]])
        self.survey_block.frame.grid(row=0, column=1, sticky="nsew", padx=2)

        # Next, there are a number of cuts depending on MJD,
        # frequency, coordinates, etc.
        self.mjd_block = RangeBlock(self.frame, "MJD")
        self.mjd_block.frame.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=2)

        # Since some of our data comes from observations of specific sources,
        # the code lets you pick only that data.
        self.source_block = ValueBlock(self.frame, "Source")
        self.source_block.frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=2)

        # You can limit the coordinates in one of two ways:
        # (1) ranges of right ascension and declination
        # (2) a disk on the sky of a certain angular size
        self.check_block = InputCheckBlock(self.frame, ["Coordinates", "Range", "Disk"])
        self.check_block.range_checkbutton.configure(command=self.coords_display)
        self.check_block.interval_checkbutton.configure(command=self.coords_display)
        self.check_block.frame.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=2)

        # The code actually creates all of the blocks for *both* options;
        # technically, toggling between them just changes which set of
        # blocks is displayed at a given time.
        # Blocks for ranges of coordinates
        self.ras_range_block = RangeBlock(self.frame, "Right ascension")
        self.decs_range_block = RangeBlock(self.frame, "Declination")
        # Blocks for a disk on the sky
        self.center_ra_block = ValueBlock(self.frame, "Central right ascension")
        self.center_dec_block = ValueBlock(self.frame, "Central declination")
        self.radius_block = ValueBlock(self.frame, "Radius (deg)")

        # Switches between the two methods of picking the coordinates
        if self.check_block.val_checkbutton.get() == True:
            # This means the user is choosing coordinates based
            # on ranges in right ascension and declination.
            self.center_ra_block.frame.grid_forget()
            self.center_dec_block.frame.grid_forget()
            self.radius_block.frame.grid_forget()
            self.ras_range_block.frame.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=2)
            self.decs_range_block.frame.grid(row=5, column=0, columnspan=2, sticky="nsew", pady=2)
        else:
            # This means the user is choosing coordinates based
            # on a disk on the sky.
            self.ras_range_block.frame.grid_forget()
            self.decs_range_block.frame.grid_forget()
            self.center_ra_block.frame.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=2)
            self.center_dec_block.frame.grid(row=5, column=0, columnspan=2, sticky="nsew", pady=2)
            self.radius_block.frame.grid(row=6, column=0, columnspan=2, sticky="nsew", pady=2)

        # Next, we have a couple widgets allowing the user to bring
        # up a skymap or not.
        self.show_skymap_frame = tk.Frame(self.frame, width=100, highlightbackground="gray",
            highlightthickness=1)
        self.show_skymap_frame.grid(row=7, column=0, columnspan=2, sticky="nsew")
        self.show_skymap_label_text = tk.StringVar()
        self.show_skymap_label_text.set("Show skymap")
        self.show_skymap_label = tk.Label(
            self.show_skymap_frame, textvariable=self.show_skymap_label_text)
        self.show_skymap_label.grid(row=0, column=0)
        self.val_skymap_checkbutton = tk.BooleanVar(self.parent, name="skymap")
        self.parent.setvar(name="skymap", value=True)
        self.skymap_checkbutton = tk.Checkbutton(self.show_skymap_frame, text="Show",
            variable=self.val_skymap_checkbutton, onvalue=True, offvalue=False, height=2, width=10)
        self.skymap_checkbutton.grid(row=1, column=0)

        # Finally, there are a set of buttons at the bottom of the
        # window, which are fairly self-explanatory.
        self.button_frame = tk.Frame(self.frame)
        self.button_frame.grid(row=8, column=0, columnspan=2, sticky=tk.W)
        self.submit_button = tk.Button(self.button_frame, text="Generate", command=self.generate)
        self.submit_button.grid(row=0, column=0, sticky=tk.W)
        self.help_button = tk.Button(self.button_frame, text="Help", command=self.get_help)
        self.help_button.grid(row=0, column=1, sticky=tk.W)
        self.quit_button = tk.Button(self.button_frame, text="Quit", command=self.quit)
        self.quit_button.grid(row=0, column=2, sticky=tk.W)
        
    def check_parent_survey_choice(self, *args):
        """
        
        Populates the second dropdown menu with the surveys contained
        within the chosen parent survey.
        
        This was coded using the pattern from
        https://stackoverflow.com/a/17581364/6535830
        It's the least bad way of doing this; getting it to work
        took me over half an hour, and I wouldn't advise trying
        to optimize it. -- Graham
        
        """
        
        self.survey_block.dropdown["menu"].delete(0, tk.END)
        surveys = self.survey_options_dict[self.parent_survey_block.dropdown_value.get()]
        self.survey_block.dropdown_value.set(surveys[0])
        for choice in surveys:
            self.survey_block.dropdown["menu"].add_command(
                label=choice, command=tk._setit(self.survey_block.dropdown_value, choice))

    def coords_display(self):
        """
        
        Switches between the two means of selecting coordinates.
        There's some duplication of code between this and the class's
        __init__() function, but it's difficult to avoid that.
        
        """
        
        if self.check_block.val_checkbutton.get() == True:
            # This means the user is choosing coordinates based
            # on ranges in right ascension and declination.
            self.center_ra_block.frame.grid_forget()
            self.center_dec_block.frame.grid_forget()
            self.radius_block.frame.grid_forget()
            self.ras_range_block.frame.grid(row=4, column=0, sticky="nsew", pady=2)
            self.decs_range_block.frame.grid(row=5, column=0, sticky="nsew", pady=2)
        else:
            # This means the user is choosing coordinates based
            # on a disk on the sky.
            self.ras_range_block.frame.grid_forget()
            self.decs_range_block.frame.grid_forget()
            self.center_ra_block.frame.grid(row=4, column=0, columnspan=3, sticky="nsew", pady=2)
            self.center_dec_block.frame.grid(row=5, column=0, columnspan=3, sticky="nsew", pady=2)
            self.radius_block.frame.grid(row=6, column=0, columnspan=3, sticky="nsew", pady=2)

    def generate(self):
        """
        
        Selects all data fulfilling the desired criteria, and creates the
        main navigation window.
        
        """
        
        self.chosen_parent_survey = self.parent_survey_block.dropdown_value.get()
        self.chosen_survey = self.survey_block.dropdown_value.get()
        
        # MJD
        
        self.low_mjd = self.mjd_block.low_entry.get()
        self.high_mjd = self.mjd_block.high_entry.get()
        try:
            self.low_mjd = float(self.low_mjd)
        except ValueError:
            if self.low_mjd != '':
                print('Invalid value {} for low MJD!'.format(self.low_mjd))
            self.low_mjd = 45000
        try:
            self.high_mjd = float(self.high_mjd)
        except ValueError:
            if self.high_mjd != '':
                print('Invalid value {} for high MJD!'.format(self.high_mjd))
            self.high_mjd = 63000
        
        # Source
        
        self.source = self.source_block.entry.get()
                
        ## Coordinates
        
        if self.check_block.val_checkbutton.get() == True:
            self.low_ra = self.ras_range_block.low_entry.get()
            self.high_ra = self.ras_range_block.high_entry.get()
            try:
                self.low_ra = float(self.low_ra)
            except ValueError:
                if self.low_ra != '':
                    print('Invalid value {} for low right ascension!'.format(self.low_ra))
                self.low_ra = 0
            try:
                self.high_ra = float(self.high_ra)
            except ValueError:
                if self.high_ra != '':
                    print('Invalid value {} for high right ascension!'.format(self.high_ra))
                self.high_ra = 360
            self.low_dec = self.decs_range_block.low_entry.get()
            self.high_dec = self.decs_range_block.high_entry.get()
            try:
                self.low_dec = float(self.low_dec)
            except ValueError:
                if self.low_dec != '':
                    print('Invalid value {} for low declination!'.format(self.low_dec))
                self.low_dec = -90
            try:
                self.high_dec = float(self.high_dec)
            except ValueError:
                if self.high_dec != '':
                    print('Invalid value {} for high declination!'.format(self.high_dec))
                self.high_dec = 90
        else:
            self.center_ra = self.center_ra_block.entry.get()
            self.center_dec = self.center_dec_block.entry.get()
            self.radius = self.radius_block.entry.get()
            try:
                self.center_ra = float(self.center_ra)
            except ValueError:
                if self.center_ra != '':
                    print('Invalid value {} for center right ascension!'.format(self.center_ra))
                self.center_ra = None
            try:
                self.center_dec = float(self.center_dec)
            except ValueError:
                if self.center_dec != '':
                    print('Invalid value {} for center declination!'.format(self.center_dec))
                self.center_dec = None
            try:
                self.radius = float(self.radius)
            except ValueError:
                if self.radius != '':
                    print('Invalid value {} for radius!'.format(self.radius))
                self.radius = 10**3 # encompasses entire sky
            if self.center_ra == None or self.center_dec == None:
                self.center_ra = 180
                self.center_dec = 0
                self.radius = 10**3 # encompasses entire sky

        if self.source == '':
            pointing_query = {"start_date_time": {"$gte": self.low_mjd, "$lte": self.high_mjd},
                              "survey": {"$eq": self.chosen_survey}}
        else:
            pointing_query = {"start_date_time": {"$gte": self.low_mjd, "$lte": self.high_mjd},
                              "survey": {"$eq": self.chosen_survey}, "source_name": {"$eq": self.source}}
        
        self.pointing_data = requests.get("{}data/search_data".format(tpp_url),
            json=pointing_query, headers=headers_file).json()
        
        survey_query = {"survey": {"$eq": self.chosen_survey}}
        
        self.survey_data = requests.get("{}survey/search_data".format(tpp_url),
            json=survey_query, headers=headers_file).json()
        
        self.generate_popup = tk.Toplevel()

        if len(self.pointing_data) != 0:
            self.info = GlobalInfoWindow(self.generate_popup, self.chosen_survey, self.chosen_parent_survey,
                self.pointing_data, self.survey_data, show_skymap=self.val_skymap_checkbutton.get())
        else:
            self.no_pointings_popup = PopupWindow(self.generate_popup, "No pointings found!")
        
    def get_help(self):
        """
        
        Creates a pop-up box providing helpful information for
        weary travelers.
        
        """
        
        self.get_help_popup = tk.Toplevel()
        
        self.help_text = "Hey there! This program is a GUI for launching jobs for TPP.\n" +\
                         "It connects to the TPP database, allowing the user to find jobs\n" +\
                         "from a particular that survey that need processing and then\n" +\
                         "launch them using Globus.\n\n" +\
                         "For questions, comments, concerns and music recommendations,\n" +\
                         "ask Graham!"
        
        self.get_help_window = PopupWindow(self.get_help_popup, self.help_text, "left")

    def quit(self):
        """
        
        Closes the Launcher window.
        
        """
        
        self.parent.destroy()
        
class DropDownBlock(tk.Frame):
    """
    
    This creates a block with a dropdown menu with a set of options.
    I've written it for the sake of convenience.
    
    Input:
        parent: the object in which to place the block
        text: the label to be placed next to the menu (string)
        options: a list of choices for the user (list of strings)
    
    """
    def __init__(self, parent, text, options):
        tk.Frame.__init__(self, parent)
        
        self.parent = parent
        
        self.frame = tk.Frame(self.parent, highlightbackground="gray", highlightthickness=1)
        
        self.label_text = tk.StringVar()
        self.label_text.set(text)
        self.label = tk.Label(self.frame, textvariable=self.label_text)
        self.label.grid(row=0, column=0)
        self.dropdown_value = tk.StringVar()
        self.dropdown_value.set(options[0])
        self.dropdown = tk.OptionMenu(self.frame, self.dropdown_value, *options)
        self.dropdown.grid(row=1, column=0)

class ValueBlock(tk.Frame):
    """
    
    This creates a block that allows the user to type in a single value.
    I've written it for the sake of convenience.
    
    Input:
        parent: the object in which to place the block
        text: the label to be placed next to the entry space (string)
    
    """
    def __init__(self, parent, text):
        tk.Frame.__init__(self, parent)
        
        self.parent = parent

        self.frame = tk.Frame(
            self.parent, width=100, highlightbackground="gray", highlightthickness=1)
        
        self.label_text = tk.StringVar()
        self.label_text.set(text)
        self.label = tk.Label(self.frame, textvariable=self.label_text)
        self.label.grid(row=0, column=0, sticky=tk.W)
        self.entry = tk.Entry(self.frame)
        self.entry.grid(row=1, column=0, sticky=tk.W)

class RangeBlock(tk.Frame):
    """
    
    This creates a block that allows the user to choose all pointings
    with parameters within the specified range of values. I've written
    it for the sake of convenience.
    
    Input:
        parent: the object in which to place the block
        text: the label to be placed next to the entry spaces (string)
    
    """
    def __init__(self, parent, text):
        tk.Frame.__init__(self, parent)
        
        self.parent = parent

        self.frame = tk.Frame(
            self.parent, highlightbackground="gray", highlightthickness=1)
        
        self.label_text = tk.StringVar()
        self.label_text.set(text)
        self.label = tk.Label(self.frame, textvariable=self.label_text)
        self.label.grid(row=0, column=0, columnspan=4, sticky=tk.W)
        self.low_label_text = tk.StringVar()
        self.low_label_text.set("Low")
        self.low_label = tk.Label(self.frame, textvariable=self.low_label_text)
        self.low_label.grid(row=1, column=0, sticky=tk.W)
        self.low_entry = tk.Entry(self.frame)
        self.low_entry.grid(row=1, column=1, sticky=tk.W)
        self.high_label_text = tk.StringVar()
        self.high_label_text.set("High")
        self.high_label = tk.Label(self.frame, textvariable=self.high_label_text)
        self.high_label.grid(row=1, column=2, sticky=tk.W)
        self.high_entry = tk.Entry(self.frame)
        self.high_entry.grid(row=1, column=3, sticky=tk.W)

class InputCheckBlock(tk.Frame):
    """
    
    This creates a block that allows the user to select or unselect
    a specific value, which should be used to toggle between two
    settings. It's only used to switch between the two options for
    restricting coordinates, which is the reason for the names of
    the last couple of attributes.
    
    Input:
        parent: the object in which to place the block
        text: the label to be placed next to the checkbox (string)
    
    """
    def __init__(self, parent, text):
        tk.Frame.__init__(self, parent)

        self.parent = parent

        self.frame = tk.Frame(self.parent, highlightbackground='gray', highlightthickness=1)

        self.val_checkbutton = tk.BooleanVar(self.parent, name="check")
        self.parent.setvar(name="check", value=True)

        self.label_text = tk.StringVar()
        self.label_text.set(text[0])
        self.label = tk.Label(self.frame, textvariable=self.label_text)
        self.label.grid(row=0, column=0, columnspan=2, sticky=tk.W)
        
        self.range_checkbutton = tk.Checkbutton(self.frame, text=text[1],
            variable=self.val_checkbutton, onvalue=True, offvalue=False, height=2, width=10)
        self.range_checkbutton.grid(row=1, column=0, sticky=tk.W)
        self.interval_checkbutton = tk.Checkbutton(self.frame, text=text[2],
            variable=self.val_checkbutton, onvalue=False, offvalue=True, height=2, width=10)
        self.interval_checkbutton.grid(row=1, column=1, sticky=tk.W)

class GlobalInfoWindow(tk.Frame):
    """
    
    This creates the window with which the user looks at the selected
    pointings, and can choose to process them and get information about
    both the survey as a whole and individual pointings.
    
    Input:
        parent: the object in which to place the window
        survey: the survey being inspected (string)
        parent_survey: the name of the parent survey (string)
        pointing_data: database information on the pointings (list)
        survey_data: database information on the survey (list)
        show_skymap: whether to create a skymap of the pointings (boolean)
    
    """ 
    def __init__(self, parent, survey, parent_survey, pointing_data, survey_data, show_skymap=True):
        tk.Frame.__init__(self, parent)

        self.parent = parent

        self.survey = survey
        self.parent_survey = parent_survey
        self.pointing_data = pointing_data
        self.survey_data = survey_data
        
        self.IDs = [pointing['_id'] for pointing in self.pointing_data]
        self.MJDs = np.array([pointing['start_date_time'] for pointing in self.pointing_data])
        self.ras = np.array([pointing['ra_j'] for pointing in self.pointing_data])
        self.decs = np.array([pointing['dec_j'] for pointing in self.pointing_data])
        
        self.N = len(self.IDs)
        self.MJD_min = np.min(self.MJDs)
        self.MJD_max = np.max(self.MJDs)
        self.freq_min = self.survey_data[0]['f_low']
        self.freq_max = self.survey_data[0]['f_hi']
        
        # To properly plot the pointings, we need to shift the right ascensions
        # a bit. It's an awkward trick, but it works.
        self.plot_ras = []
        self.plot_decs = []
        for i in range(self.N):
            self.plot_ras.append(self.ras[i] * (2*np.pi/360))
            self.plot_decs.append(self.decs[i] * (2*np.pi/360))
            while self.plot_ras[i] > np.pi:
                self.plot_ras[i] -= 2*np.pi
        
        # We now query the database to figure out which of these pointings
        # have been processed and which haven't. If one has been submitted,
        # an entry is created; if there's no entry, it means the pointing
        # has not yet been submitted!
        self.statuses = []
        for i in range(len(self.IDs)):
            ID_query = {"dataID": {"$eq": self.IDs[i]}}
            ID_data = requests.get("{}survey/search_data".format(tpp_url),
                json=ID_query, headers=headers_file).json()
            if ID_data == []:
                self.statuses.append('Unprocessed')
            else:
                info = ID_data[0]
                is_completed = info["completed"]
                if is_completed == True:
                    self.statuses.append('Completed')
                else:
                    self.statuses.append('Active')
        self.statuses = np.array(self.statuses)
        
        # number of completed jobs
        self.N_completed = len(self.statuses[(self.statuses == 'Completed')])
        
        # number of active jobs
        self.N_active = len(self.statuses[(self.statuses == 'Active')])
        
        self.frame = tk.Frame(self.parent)
        self.frame.grid(row=0, column=0, sticky=tk.W)

        self.button_frame = tk.Frame(self.frame)
        self.button_frame.grid(row=0, column=0, columnspan=3, sticky=tk.W)
        
        self.info_frame = tk.Frame(self.frame, width=50)
        self.info_frame.grid(row=1, column=0, sticky=tk.W)

        self.jobs_frame = tk.Frame(self.frame)
        self.jobs_frame.grid(row=1, column=1, sticky=tk.W)

        self.plot_frame = tk.Frame(self.frame)
        self.plot_frame.grid(row=1, column=2, sticky=tk.W)
        
        self.info_text = "Survey:\n" +\
                         "    {}\n".format(self.survey) +\
                         "Parent survey:\n" +\
                         "    {}\n".format(self.parent_survey) +\
                         "MJD range:\n" +\
                         "    ({}, {})\n".format(self.MJD_min, self.MJD_max) +\
                         "Frequency range (MHz):\n" +\
                         "    ({}, {})\n".format(self.freq_min, self.freq_max) +\
                         "Pointings:\n" +\
                         "    {}\n".format(self.N) +\
                         "Number processed:\n" +\
                         "    {} ({:.2f})%\n".format(self.N_completed, self.N_completed/self.N) +\
                         "Number active:\n" +\
                         "    {} ({:.2f})%".format(self.N_active, self.N_active/self.N)
        
        # We create three specific boxes: One for all of the pointings,
        # including general survey information, and one each for unprocessed
        # and active jobs. The GUI isn't designed to examine pointings
        # that have already been processed, which is why those don't have
        # their own special section -- I think Morrigan is writing code
        # for that!
        self.unprocessed_info_box = InfoBox(self.info_frame, self.info_text, self.IDs, self.MJDs,
            self.ras, self.decs, self.statuses, "Survey information", space_text="All jobs")
        self.unprocessed_info_box.frame.grid(row=0, column=0, sticky=tk.W)
        
        self.current_jobs_info_box = InfoBox(self.jobs_frame, None, self.IDs, self.MJDs, self.ras, self.decs,
            self.statuses, "Unprocessed jobs", statuses_to_show=["Unprocessed"], show_text=False)
        self.current_jobs_info_box.frame.grid(row=0, column=0, sticky=tk.W)
        
        self.recent_jobs_info_box = InfoBox(self.jobs_frame, None, self.IDs, self.MJDs, self.ras, self.decs,
            self.statuses, "Active jobs", statuses_to_show=["Active"], show_text=False)
        self.recent_jobs_info_box.frame.grid(row=1, column=0, sticky=tk.W)

        self.launch_all_button = tk.Button(self.button_frame, text="Launch All", command=self.launch_all)
        self.launch_all_button.grid(row=0, column=0, sticky=tk.W)
        
        # I've made showing the skymap optional because it may be slow to
        # load if there are a lot of pointings. I'm not sure why I have two
        # for loops here, but will check that out at some point!
        # -- Graham (9/20/24)
        if show_skymap == True:
            self.save_skymap_button = tk.Button(self.button_frame, text="Save skymap", command=self.save_skymap_box)
            self.save_skymap_button.grid(row=0, column=1, sticky=tk.W)

        if show_skymap == True:
            self.skymap_figure = plt.Figure()
            self.skymap_canvas = FigureCanvasTkAgg(self.skymap_figure, master=self.plot_frame)
            self.skymap_canvas.get_tk_widget().grid(row=0, column=0, columnspan=4)
            self.skymap_canvas.get_tk_widget().grid_propagate()
            self.ax1 = self.skymap_figure.add_subplot(111, projection="mollweide")
            self.ax1.scatter(self.plot_ras, self.plot_decs, color="red", label=self.survey, alpha=0.3, s=10)
            self.ax1.legend(loc=(0.75, 1))
            self.skymap_canvas.draw()
            
        self.help_button = tk.Button(self.button_frame, text="Help", command=self.get_help)
        self.help_button.grid(row=0, column=2, sticky=tk.W)
        
        self.quit_button = tk.Button(self.button_frame, text="Quit", command=self.quit)
        self.quit_button.grid(row=0, column=3, sticky=tk.W)

    def save_skymap_box(self):
        """
        
        Creates a pop-up allowing the user to save the skymap as an
        image for future use.
        
        """
        
        self.save_skymap_popup = tk.Toplevel()

        self.save_skymap_popup_frame = tk.Frame(self.save_skymap_popup)
        self.save_skymap_popup_frame.grid(row=0, column=0, sticky=tk.W)

        self.save_skymap_popup_label_text = tk.StringVar()
        self.save_skymap_popup_label_text.set("File name:")
        self.save_skymap_popup_label = tk.Label(
            self.save_skymap_popup_frame, textvariable=self.save_skymap_popup_label_text)
        self.save_skymap_popup_label.grid(row=0, column=0)
        self.save_skymap_popup_entry = tk.Entry(
            self.save_skymap_popup_frame)
        self.save_skymap_popup_entry.grid(row=1, column=0)
        self.save_skymap_popup_button = tk.Button(
            self.save_skymap_popup_frame, text="Save", command=self.save_skymap)
        self.save_skymap_popup_button.grid(row=2, column=0)

    def launch_all(self):
        """
        
        Launches a set of jobs using launcher.py.
        
        """
        
        num_bad_statuses = 0
        num_good_statuses = 0
        for i in range(len(self.statuses)):
            if self.statuses[i] != "Unprocessed":
                num_bad_statuses += 1
            else:
                num_good_statuses += 1
                # make this do something!! Call the launcher:
                #
                # command = "/path/to/launcher.py -d self.IDs[i]"
                # split_command = shlex.split(command)
                # subprocess.Popen(split_command, start_new_session=True)
        self.launch_result_popup = tk.Toplevel()
        self.launch_result_window = PopupWindow(self.launch_result_popup,
            "{} jobs launched; {} jobs cannot be processed.".format(num_good_statuses, num_bad_statuses))
        
    def save_skymap(self):
        """
        
        Actually saves the skymap. This is called by the "save" button
        in the pop-up box.
        
        """
            
        self.skymap_figure.savefig(self.save_skymap_popup_entry.get())
        self.save_skymap_popup.destroy()

    def get_help(self):
        """
        
        Creates a pop-up box providing helpful information for
        weary travelers.
        
        """
        
        self.get_help_popup = tk.Toplevel()
        
        self.help_text = "Hey there! This program is a GUI for launching jobs for TPP.\n" +\
                         "It connects to the TPP database, allowing the user to find jobs\n" +\
                         "from a particular that survey that need processing and then\n" +\
                         "launch them using Globus.\n\n" +\
                         "For questions, comments, concerns and music recommendations,\n" +\
                         "ask Graham!"
        
        self.get_help_window = PopupWindow(self.get_help_popup, self.help_text, "left")

    def quit(self):
        """
        
        Closes the GlobalInfoBox window.
        
        """
        
        self.parent.destroy()
        
class InfoBox(tk.Frame):
    """
    
    This is a box showing information about a set of pointings. It is used
    by GlobalInfoBox to display information about the survey and/or to list
    the IDs of the pointings within.
    
    Input:
        parent: the object in which to place the block
        text: the information to display (string)
        IDs: the IDs of the pointings (list of strings)
        MJDs: the MJDs of the pointings (list of floats)
        ras: the right ascensions of the pointings (list of floats)
        decs: the declinations of the pointings (list of floats)
        statuses: the processing statuses of the pointings (list of strings)
        title: the title of the pane (string)
        show_text: whether to show the information (boolean)
        statuses_to_show: which subclass(es) of pointings to show (list of strings)
        space_text: text to be inserted to make the spacing between
                    objects nice (string)
    
    """
    def __init__(self, parent, text, IDs, MJDs, ras, decs, statuses, title, show_text=True,
        statuses_to_show=["Unprocessed", "Active", "Completed"], space_text=""):
        
        self.parent = parent
        
        self.frame = tk.Frame(self.parent)
        self.frame.grid(row=0, column=0, sticky=tk.W)
        
        self.text = text
        self.IDs = IDs
        self.MJDs = MJDs
        self.ras = ras
        self.decs = decs
        self.statuses = statuses
        
        self.space_text = space_text
        
        self.N = len(self.IDs)
        
        self.title = tk.Label(self.frame, width=50, text=title)
        self.title.grid(row=0, column=0)
         
        if show_text == True:
            self.info_box = tk.Text(self.frame, width=50, background="lightgray")
            self.info_box.grid(row=1, column=0, sticky=tk.W)
            self.info_box.insert(tk.INSERT, self.text)
            self.info_box.config(state=tk.DISABLED)

            self.space_var = tk.StringVar()
            self.space_var.set(self.space_text)
            self.space_label = tk.Label(self.frame, textvariable=self.space_var)
            self.space_label.grid(row=2, column=0)

        self.pointing_list_box = scrolledtext.ScrolledText(self.frame, width=50, background="lightgray")
        self.pointing_list_box.grid(row=3, column=0, sticky=tk.W)
        self.pointing_list_box.tag_config("tag")
        self.pointing_list_box.tag_bind("tag", "<Button-1>", self.select_id)
        
        # We have to insert the pointing information here one by one
        # so we can uniquely identify each one for select_id().
        for i in range(self.N):
            if self.statuses[i] in statuses_to_show:
                self.pointing_list_box.insert(tk.INSERT, self.IDs[i], "tag")
                self.pointing_list_box.insert(tk.INSERT, "\n")
        self.pointing_list_box.delete("end-2c", tk.END)

        self.pointing_list_box.config(state=tk.DISABLED)
        
    def select_id(self, event):
        """
        
        Determines the ID of the desired pointing based on the coordinates
        of the mouse when the user clicks. For information on how this
        works, see https://stackoverflow.com/a/33957256/6535830.
        
        """
        
        line_index = event.widget.index("@%s,%s" % (event.x, event.y))

        tag_indices = list(event.widget.tag_ranges("tag"))
        
        for start, end in zip(tag_indices[0::2], tag_indices[1::2]):
            if event.widget.compare(start, '<=', line_index) and event.widget.compare(line_index, '<', end):
                ID = event.widget.get(start, end)

        ID_index = list(self.IDs).index(ID)
        MJD = self.MJDs[ID_index]
        ra = self.ras[ID_index]
        dec = self.decs[ID_index]
        status = self.statuses[ID_index]
        
        self.pointing_popup = tk.Toplevel()
        
        self.launch_pointing = LaunchPointingWindow(self.pointing_popup, ID, MJD, ra, dec, status)
        
class LaunchPointingWindow(tk.Frame):
    """
    
    This creates the window with which the user submits a job for a pointing.
    
    Input:
        parent: the object in which to place the window
        ID: the ID of the pointing (string)
        MJD: the MJD of the pointing (float)
        ra: the right ascension of the pointing (float)
        dec: the declination of the pointing (float)
        status: the processing status of the pointing (string)
    
    """
    def __init__(self, parent, ID, MJD, ra, dec, status):
        tk.Frame.__init__(self, parent)
        
        self.parent = parent
        
        self.ID = ID
        self.MJD = MJD
        self.ra = ra
        self.dec = dec
        self.status = status
        
        self.frame = tk.Frame(self.parent)
        self.frame.grid(row=0, column=0, sticky=tk.W)
        
        self.info_frame = tk.Frame(self.parent)
        self.info_frame.grid(row=0, column=0)
        
        self.info_box = tk.Text(self.info_frame, height=5, width=50, background="lightgray")
        self.info_box.grid(row=0, column=0)
        self.info_box.insert(tk.INSERT,
                             "ID: {}\n".format(self.ID) +\
                             "MJD: {}\n".format(self.MJD) +\
                             "RA: {}\n".format(self.ra) +\
                             "Dec: {}\n".format(self.dec) +\
                             "Status: {}\n".format(self.status))
        self.info_box.config(state=tk.DISABLED)
        
        self.button_frame = tk.Frame(self.parent)
        self.button_frame.grid(row=1, column=0)
        
        self.launch_button = tk.Button(self.button_frame, text="Launch", command=self.launch)
        self.launch_button.grid(row=0, column=0)
        
        self.quit_button = tk.Button(self.button_frame, text="Quit", command=self.quit)
        self.quit_button.grid(row=0, column=1)
        
    def launch(self):
        """
        
        Submits a job using launcher.py
        
        """
        
        if self.status != "Unprocessed":
            self.launch_warning_popup = tk.Toplevel()
            self.launch_warning_window = PopupWindow(self.launch_warning_popup,
                "Warning! Pointing status is {} and cannot be processed.".format(self.status))
        else:
            # make this do something!! Call the launcher:
            #
            # command = "/path/to/launcher.py -d self.ID"
            # split_command = shlex.split(command)
            # subprocess.Popen(split_command, start_new_session=True)
            #
            self.launch_result_popup = tk.Toplevel()
            self.launch_result_window = PopupWindow(self.launch_result_popup,
                "Job launched!")
            self.quit()

    def quit(self):
        """
        
        Closes the LaunchPointingWindow.
        
        """
        
        self.parent.destroy()
        
class PopupWindow(tk.Frame):
    """
    
    This creates a popup window with a message of choice.
    
    Input:
        parent: the object in which to place the window
        text: the text to display (string)
    
    """
    def __init__(self, parent, text, justify="center"):
        tk.Frame.__init__(self, parent)
        
        self.parent = parent
        self.text = text
        self.justify = justify
        
        self.frame = tk.Frame(self.parent)
        self.frame.grid(row=0, column=0, sticky=tk.W)
        
        self.text_var = tk.StringVar()
        self.text_var.set(self.text)
        self.text_label = tk.Label(self.frame, textvariable=self.text_var, justify=self.justify)
        self.text_label.grid(row=0, column=0)
        
        self.quit_button = tk.Button(self.frame, text="Okay", command=self.quit)
        self.quit_button.grid(row=1, column=0)
        
    def quit(self):
        """
        
        Closes the PopupWindow.
        
        """ 
        
        self.parent.destroy()

def main():
    
    root = tk.Tk()
    root.title("Mission Control")
    LAUNCHER = Launcher(root)
    LAUNCHER.mainloop()

if __name__ == "__main__":
    main()
