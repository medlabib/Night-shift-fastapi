# api

# API Documentation

## Description

This API is used to schedule doctors for shifts in a hospital. It takes into account the number of doctors needed for each shift, the doctor's grade, and their availability. The scheduling algorithm aims to minimize the difference in points earned by each doctor.

## Endpoints

This API has only one endpoint:

### /schedule

This endpoint schedules doctors for shifts based on the input parameters.

### Request Parameters

- `start_date` (required): The start date of the scheduling period. Format: YYYY-MM-DD.
- `end_date` (required): The end date of the scheduling period. Format: YYYY-MM-DD.
- `grades` (required): A list of grades, e.g. ['level 1', 'level 2', 'level 3'].
- `same_num_doctors` (optional): Whether to use the same number of doctors for each night. Default: "N". Possible values: "Y" or "N".
- `num_doctors_per_night` (optional): A dictionary with the number of doctors needed for each night. Only used if `same_num_doctors` is set to "N".
- `doctor_not_present` (optional): A dictionary with doctors who are not available on certain days.
- `holidays` (optional): A list of holidays.

### Response Parameters

- `schedule`: A dictionary with the scheduled shifts. The keys are the dates, and the values are a list of dictionaries with the doctor's name and the points earned for that shift.
- `points`: A dictionary with the points earned by each doctor for each grade.
- `num_shifts`: A dictionary with the number of shifts worked by each doctor for each grade.
- `num_weekend_shifts`: A dictionary with the number of weekend shifts worked by each doctor for each grade.
- `schedule_name`: A string with the name of the schedule.
- `score`: A float with the score of the schedule.

### Example Request

```
import requests

url = "<https://example.com/schedule>"
payload = {
    "start_date": "2022-03-01",
    "end_date": "2022-03-10",
    "grades": ["level 1", "level 2", "level 3"],
    "same_num_doctors": "N",
    "num_doctors_per_night": {
        "2022-03-01": 2,
        "2022-03-02": 3,
        "2022-03-03": 2,
        "2022-03-04": 3,
        "2022-03-05": 2,
        "2022-03-06": 3,
        "2022-03-07": 2
    }
}
response = requests.post(url, json=payload)
print(response.json())

```

### Example Response

```
{
    "schedule": {
        "2022-03-01": [
            {
                "Doctor A": 1,
                "Doctor B": 1
            },
            {
                "Doctor C": 1,
                "Doctor D": 1
            }
        ],
        "2022-03-02": [
            {
                "Doctor E": 1,
                "Doctor F": 1,
                "Doctor G": 1
            },
            {
                "Doctor H": 1,
                "Doctor I": 1,
                "Doctor J": 1
            }
        ],
        "2022-03-03": [
            {
                "Doctor K": 1,
                "Doctor L": 1
            },
            {
                "Doctor M": 1,
                "Doctor N": 1
            }
        ],
        "2022-03-04": [
            {
                "Doctor O": 1,
                "Doctor P": 1,
                "Doctor Q": 1
            },
            {
                "Doctor R": 1,
                "Doctor S":
```