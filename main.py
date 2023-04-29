import datetime
import random
from collections import defaultdict
from typing import List, Dict, Optional
import numpy as np
import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
import json
import sqlite3
import uuid

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

class ScheduleInput(BaseModel):
    doctor_names: str
    start_date: str
    end_date: str
    same_num_doctors: str
    num_doctors: Optional[int]
    num_doctors_per_night: Optional[Dict[str, int]]
    holiday_days: str
    find: int


def parse_date(date_str):
    return datetime.datetime.strptime(date_str, "%Y-%m-%d").date()


@app.get("/")
def index():
    return "Api deployed successfully"


@app.post("/schedule")
def schedule(data: ScheduleInput):
    # Get the input fields from the POST request
    doctor_names = data.doctor_names
    start_date = datetime.datetime.strptime(data.start_date, "%Y-%m-%d").date()
    end_date = datetime.datetime.strptime(data.end_date, "%Y-%m-%d").date()
    same_num_doctors = data.same_num_doctors  # True or False
    num_doctors_per_night = []
    if same_num_doctors == "Y":
        num_doctors = data.num_doctors
        num_doctors_per_night = [int(num_doctors) for _ in
                                 range((end_date - start_date).days + 1)]  # Same number for all nights
    holiday_days = data.holiday_days.strip()
    find = data.find
    # Process holiday input
    if holiday_days:
        holidays = [parse_date(day) for day in holiday_days.split(",")]
    else:
        holidays = []
     
    # Constants
    DOCTORS = doctor_names.split(",")
    MAX_POINTS_DIFFERENCE = 1
    score = float('inf')
    # Create a list of days in the scheduling period
    days = []
    current_date = start_date
    while current_date <= end_date:
        days.append(current_date)
        current_date += datetime.timedelta(days=1)
    if same_num_doctors != "Y":
        # num_doctors_per_night is a [list] of number of doctors for each night, e.g. [2, 3, 2, 3, 2, 3, 2], num_doctors_per_night is originally a dict {day: num_doctors }
        num_doctors_per_night+= [int(data.num_doctors_per_night[day]) for day in data.num_doctors_per_night]

    # Create a dictionary with points for each day
    points_per_day = {}
    for day in days:
        if day in holidays:
            points_per_day[day] = 2
        elif day.weekday() == 5:
            points_per_day[day] = 1.5
        elif day.weekday() == 6:
            points_per_day[day] = 2
        else:
            points_per_day[day] = 1

    # Call the existing function to retrieve the other user inputs
    # Perform scheduling logic
    num_doctors = len(DOCTORS)
    # transform data to json
    data_json = [data.start_date, data.end_date, num_doctors, data.doctor_names,data.same_num_doctors, data.holiday_days, data.num_doctors_per_night, data.find]
    # Other constants
    def assign_shift(day, doctor, points_value):
        schedule.append((day, doctor, points_value))
        points[doctor] += points_value
        shifts.append((day.day, doctor))

    def calculate_shift_stats(schedule):
        num_shifts = defaultdict(int)
        num_weekend_shifts = defaultdict(int)

        for day, doctor, _ in schedule:
            num_shifts[doctor] += 1

            if day.strftime('%A') in ['Saturday', 'Sunday']:
                num_weekend_shifts[doctor] += 1
        return num_shifts, num_weekend_shifts
    # Initialize variables
    best_difference = float('inf')
    best_schedules = []
    # Use pandas date_range to generate a list of days
    days = pd.date_range(start_date, end_date)

    for i in range(find):
        schedule = []
        points = {doctor: 0 for doctor in DOCTORS}
        shifts = []
        for day, num_doctors_this_night in zip(days, num_doctors_per_night):
            # Get points for the day
            points_value = points_per_day[day.to_pydatetime().date()]
            # Choose doctors
            exclude_doctors = [doc for _, doc in shifts[-int((num_doctors - np.ceil(num_doctors / 3))):]]
            available_doctors = [d for d in DOCTORS if d not in exclude_doctors]
            doctors = random.sample(available_doctors, num_doctors_this_night)

            # Assign shift to the doctors
            [assign_shift(day, doctor, points_value) for doctor in doctors]

        # Calculate maximum and minimum points earned by the doctors
        max_points = max(points.values())
        min_points = min(points.values())
        # Calculate difference in points between the doctors
        difference = max_points - min_points

        # If difference is better, save the schedule
        if difference < best_difference:
            best_difference = difference
            best_schedules = [schedule]
        elif difference == best_difference:
            best_schedules.append(schedule)

        # Initialize the variables to store the optimal schedules and their stats
    optimal_schedules = []
    min_difference_in_points = float('inf')

    # Loop through the best schedules and apply the logic to find the optimal schedules
    # make the for loop below into a function
    for schedule in best_schedules:
        num_shifts, num_weekend_shifts = calculate_shift_stats(schedule)

        # Calculate the differences in shifts and weekend shifts between doctors
        shift_difference = max(num_shifts.values()) - min(num_shifts.values())
        weekend_shift_difference = max(num_weekend_shifts.values()) - min(num_weekend_shifts.values())

        # Calculate the score for the spacing of shifts between doctors
        spacing_scores = []
        for doctor in num_shifts.keys():
            shifts = [(int(day.strftime('%d')), doc, pts) for day, doc, pts in schedule if doc == doctor]
            if len(shifts) > 1:
                spacings = np.diff([shift[0] for shift in shifts])
                spacing_scores.append(spacings)

        # Calculate the variance of the spacings for each doctor
        variances = [np.var(spacing) for spacing in spacing_scores]

        # Calculate the sum of the variances
        total_variance = sum(variances)

        # Calculate the sum of the differences and the spacing score
        total_difference = total_variance + shift_difference + weekend_shift_difference

        # Update the optimal schedules and their stats if necessary
        if total_difference < min_difference_in_points:
            min_difference_in_points = total_difference
            optimal_schedules = [schedule]
            score = total_difference
        elif total_difference == min_difference_in_points:
            optimal_schedules.append(schedule)

    # Add your scheduling logic here
    if len(optimal_schedules) > 0:
        # Group the schedule by days
        grouped_schedule = {}
        for day, doctor, points_value in optimal_schedules[0]:
            if day not in grouped_schedule:
                grouped_schedule[day] = []
            grouped_schedule[day].append((doctor, points_value))

    # convert datetime in grouped schedule to string
    returned_schedule = {}
    for day in grouped_schedule:
        returned_schedule[day.strftime('%Y-%m-%d')] = grouped_schedule[day]
    num_shifts, num_weekend_shifts = calculate_shift_stats(optimal_schedules[0])
    points = {doctor: 0 for doctor in DOCTORS}
    for day, doctor, points_value in optimal_schedules[0]:
        points[doctor] += points_value
    # save schedule to sqlite using uuid    
    schedule_id = uuid.uuid4()
    schedule_name = "Schedule " + str(schedule_id)
    schedule_name = schedule_name.replace(" ","")
    schedule_name = schedule_name.replace("-","")
    # create an sqlite db
    db = sqlite3.connect('schedule.db')
    # create a cursor
    c = db.cursor()
    # create a table for the schedule with rows for stats
    c.execute("CREATE TABLE IF NOT EXISTS schedule(name TEXT, parameters TEXT, schedule TEXT, points TEXT, shift_difference TEXT, weekend_shift_difference TEXT, num_shifts INT, num_weekend_shifts INT, score FLOAT)")
    # insert the schedule into the table
    c.execute("INSERT INTO schedule VALUES (?, ?, ?, ?, ?, ?,?,?,?)", (schedule_name, json.dumps(data_json), json.dumps(returned_schedule) , json.dumps(points), shift_difference, weekend_shift_difference, json.dumps(num_shifts), json.dumps(num_weekend_shifts), score))
    # commit changes
    db.commit()
    # close the connection
    db.close()
    # Return the result as a JSON response
    return {'schedule': returned_schedule, 'num_shifts': num_shifts, 'num_weekend_shifts': num_weekend_shifts,
                    'points': points, 'score': score, 'schedule_name':schedule_name}

#add a route to get schedule by schedule name
@app.get('/result/{name}')
def get_schedule(name):
    # get the schedule from the database
    print(name)
    db = sqlite3.connect('schedule.db')
    c = db.cursor()
    c.execute("SELECT * FROM schedule WHERE name = ?", (name,))
    schedule = c.fetchone()
    # close the connection
    db.close()
    # convert schedule to same format the /schedule outputs
    schedule_json = json.loads(schedule[2])
    num_shifts_json = json.loads(schedule[6])
    num_weekend_shifts_json = json.loads(schedule[7])
    score = schedule[8]
    points_json = json.loads(schedule[3])
    # return the schedule as json
    return {'schedule': schedule_json, 'num_shifts':num_shifts_json, 'num_weekend_shifts': num_weekend_shifts_json,'points': points_json, 'score': score}
 


    

