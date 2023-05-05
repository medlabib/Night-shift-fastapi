import datetime
import random
import uuid
from collections import defaultdict
from typing import List, Dict, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()


def parse_date(date_str):
    return datetime.datetime.strptime(date_str, "%Y-%m-%d").date()


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
    department_is_graded: str
    doctors_grades: Optional[Dict[str, str]]
    shift_requirements: Optional[Dict[str, List[str]]]
    grades: Optional[List[str]]
    doctor_not_present: Optional[Dict[str, str]]


@app.post("/schedule")
async def schedule(data: ScheduleInput):
    doctor_names = data.doctor_names
    start_date = datetime.datetime.strptime(data.start_date, "%Y-%m-%d").date()
    end_date = datetime.datetime.strptime(data.end_date, "%Y-%m-%d").date()
    same_num_doctors = data.same_num_doctors  # True or False
    num_doctors_per_night = []
    department_is_graded = data.department_is_graded
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
    if data.doctor_not_present is not None:
        doctor_not_present = data.doctor_not_present
    else:
        doctor_not_present = {}

    if same_num_doctors == "Y":
        num_doctors = data.num_doctors
        num_doctors_per_night = [int(num_doctors) for _ in
                                 range((end_date - start_date).days + 1)]  # Same number for all nights
    # If department is not graded
    if department_is_graded == "N":
        num_doctors = len(DOCTORS)

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

        # Create a list of days in the scheduling period
        days = []
        current_date = start_date
        while current_date <= end_date:
            days.append(current_date)
            current_date += datetime.timedelta(days=1)
        if same_num_doctors != "Y":
            # num_doctors_per_night is a [list] of number of doctors for each night, e.g. [2, 3, 2, 3, 2, 3, 2], num_doctors_per_night is originally a dict {day: num_doctors }
            num_doctors_per_night += [int(data.num_doctors_per_night[day]) for day in data.num_doctors_per_night]
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
        days = pd.date_range(start_date, end_date)
        # Initialize variables
        best_difference = float('inf')
        best_schedules = []
        for i in range(find):
            schedule = []
            points = {doctor: 0 for doctor in DOCTORS}
            shifts = []
            for day, num_doctors_this_night in zip(days, num_doctors_per_night):
                # Get points for the day
                try:
                    points_value = points_per_day[day.to_pydatetime().date()]
                    # Choose doctors
                    exclude_doctors = [doc for _, doc in shifts[-int((num_doctors - np.ceil(num_doctors / 3))):]]
                    available_doctors = [d for d in DOCTORS if d not in exclude_doctors and day.strftime(
                        '%Y-%m-%d') not in doctor_not_present.get(d, '').split(',')]
                    doctors = random.sample(available_doctors, num_doctors_this_night)
                    # Assign shift to the doctors
                    [assign_shift(day, doctor, points_value) for doctor in doctors]
                except:
                    pass
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
        score = 0
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
        doc_points = {doctor: 0 for doctor in DOCTORS}
        for day, doctor, points_value in optimal_schedules[0]:
            doc_points[doctor] += points_value
        # save schedule to sqlite using uuid
    # If department is graded
    else:
        # Get the grades and the shift requirements
        doctors_grades = data.doctors_grades
        grades = data.grades  # e.g. ['level 1', 'level 2', 'level 3']

        shift_requirements = data.shift_requirements  # e.g. [{'2022-03-01': ['level 1', 'level 2']}, {'2022-03-02': ['level 3']}]

        def assign_shift(day, doctor, points_value):
            schedule.append((day, doctor, points_value))
            points[doctor] += points_value
            shifts.append((day.day, doctor))

        def calculate_shift_stats(schedule):
            num_shifts = {}
            num_weekend_shifts = {}
            for grade in grades:
                num_shifts[grade] = defaultdict(int)
                num_weekend_shifts[grade] = defaultdict(int)
            for day, doctor, _ in schedule:
                grade = doctors_grades[doctor]
                num_shifts[grade][doctor] += 1
                if day.strftime('%A') in ['Saturday', 'Sunday']:
                    num_weekend_shifts[grade][doctor] += 1
            return num_shifts, num_weekend_shifts

        # Create a list of days in the scheduling period
        days = []
        current_date = start_date
        while current_date <= end_date:
            days.append(current_date)
            current_date += datetime.timedelta(days=1)
        if same_num_doctors != "Y":
            # num_doctors_per_night is a [list] of number of doctors for each night, e.g. [2, 3, 2, 3, 2, 3, 2], num_doctors_per_night is originally a dict {day: num_doctors }
            num_doctors_per_night += [int(data.num_doctors_per_night[day]) for day in data.num_doctors_per_night]

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

        # Initialize variables

        best_difference = float('inf')
        best_schedules = []
        days = pd.date_range(start_date, end_date)
        num_doctors = len(DOCTORS)
        for i in range(find):
            schedule = []
            points = {doctor: 0 for doctor in DOCTORS}
            shifts = []
            for day, num_doctors_this_night in zip(days, num_doctors_per_night):
                # Get points for the day
                points_value = points_per_day[day.to_pydatetime().date()]
                # Choose doctors
                exclude_doctors = [doc for _, doc in shifts[-int((num_doctors - np.ceil(num_doctors / 3))):]]
                available_doctors = [d for d in DOCTORS if d not in exclude_doctors and day.strftime(
                    '%Y-%m-%d') not in doctor_not_present.get(d, '').split(',')]
                # Assign shifts for each grade separately
                for grade in grades:
                    # Get the doctors with the current grade
                    try:
                        available_doctors_this_grade = [d for d in available_doctors if doctors_grades[d] == grade]

                        # Check if there are shift requirements for the current day and grade
                        shift_requirements_this_day = None
                        for shift_requirement in shift_requirements:
                            if day.strftime("%Y-%m-%d") in shift_requirement:
                                shift_requirements_this_day = shift_requirements[day.strftime("%Y-%m-%d")]

                        # Choose doctors for the shift based on the shift requirements and the available doctors
                        if shift_requirements_this_day is None:
                            doctors_this_shift = random.sample(available_doctors_this_grade, num_doctors_this_night)
                        else:
                            doctors_this_shift = []
                            for grade_requirement in shift_requirements_this_day:
                                num_doctors_this_grade = grade_requirement.count(grade)
                                doctors_this_grade = random.sample(
                                    [d for d in available_doctors_this_grade if doctors_grades[d] == grade],
                                    num_doctors_this_grade)
                                doctors_this_shift += doctors_this_grade

                        # Assign shift to the doctors
                        [assign_shift(day, doctor, points_value) for doctor in doctors_this_shift]
                    except:
                        pass

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
        optimal_schedules = {grade: [] for grade in grades}
        min_difference_in_points = {grade: float('inf') for grade in grades}

        # Loop through the best schedules and apply the logic to find the optimal schedules
        for schedule in best_schedules:
            num_shifts, num_weekend_shifts = calculate_shift_stats(schedule)

            # Calculate the differences in shifts and weekend shifts between doctors for each grade
            shift_difference = {grade: max(num_shifts[grade].values()) - min(num_shifts[grade].values()) for grade in
                                grades}
            weekend_shift_difference = {
                grade: max(num_weekend_shifts[grade].values()) - min(num_weekend_shifts[grade].values()) for grade in
                grades}

            # Calculate the score for the spacing of shifts between doctors for each grade
            spacing_scores = {grade: [] for grade in grades}
            for grade in grades:
                for doctor in num_shifts[grade].keys():
                    shifts = [(int(day.strftime('%d')), doc, pts) for day, doc, pts in schedule if doc == doctor]
                    if len(shifts) > 1:
                        spacings = np.diff([shift[0] for shift in shifts])
                        spacing_scores[grade].append(spacings)

            # Calculate the variance of the spacings for each doctor for each grade
            variances = {grade: [np.var(spacing) for spacing in spacing_scores[grade]] for grade in grades}

            # Calculate the sum of the variances for each grade
            total_variance = {grade: sum(variances[grade]) for grade in grades}

            # Calculate the sum of the differences and the spacing score for each grade
            total_difference = {grade: total_variance[grade] + shift_difference[grade] + weekend_shift_difference[grade]
                                for
                                grade in grades}

            # Update the optimal schedules and their stats if necessary for each grade
            for grade in grades:
                if total_difference[grade] < min_difference_in_points[grade]:
                    min_difference_in_points[grade] = total_difference[grade]
                    optimal_schedules[grade] = [schedule]
                    score = total_difference[grade]
                elif total_difference[grade] == min_difference_in_points[grade]:
                    optimal_schedules[grade].append(schedule)
        # Add your scheduling logic here
        grouped_schedule = {}
        for day, doctor, points in optimal_schedules[grades[0]][0]:
            if day not in grouped_schedule:
                grouped_schedule[day] = {}
            if doctors_grades[doctor] not in grouped_schedule[day]:
                grouped_schedule[day][doctors_grades[doctor]] = []
            grouped_schedule[day][doctors_grades[doctor]].append({doctor: points})

        num_shifts, num_weekend_shifts = calculate_shift_stats(optimal_schedules[grades[0]][0])
        # calculate points for each doctor per grade
        doc_points = {}
        for grade in grades:
            doc_points[grade] = {}
            for doctor in DOCTORS:
                if doctors_grades[doctor] == grade:
                    doc_points[grade][doctor] = 0
                    for day, doc, points in optimal_schedules[grades[0]][0]:
                        if doc == doctor and doctors_grades[doctor] == grade:
                            doc_points[grade][doctor] += points
        returned_schedule = {}
        for day, doctor, points in optimal_schedules[grades[0]][0]:
            if day not in returned_schedule:
                returned_schedule[day] = {}
            returned_schedule[day][doctor] = points
    schedule_name = "Schedule " + str(uuid.uuid4())
    return {'schedule': returned_schedule, 'points': doc_points, 'num_shifts': num_shifts,
            'num_weekend_shifts': num_weekend_shifts, 'schedule_name': schedule_name, 'score': score}
