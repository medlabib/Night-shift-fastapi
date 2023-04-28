# Api documentation

Last edited time: 19 avril 2023 03:18
Owner: Anonyme
Tags: project
Verification: Vérifiée

# Schedule API Documentation

This code is an implementation of an API that generates a schedule for doctors based on input parameters.

The API is implemented using Python 3 and the FastAPI web framework. It relies on a number of libraries including datetime, random, numpy, pandas, and pydantic.

## Endpoints

There is one endpoint defined in this API:

### `GET /`

This endpoint returns a simple message indicating that the API has been deployed successfully.

### `POST /schedule`

This endpoint generates a schedule for doctors based on the input parameters provided in the request body.

### Request Body

The request body must be a JSON object with the following fields:

- `doctor_names`: A comma-separated string of the names of the doctors available for scheduling.
- `start_date`: The start date for the scheduling period in the format `YYYY-MM-DD`.
- `end_date`: The end date for the scheduling period in the format `YYYY-MM-DD`.
- `same_num_doctors`: A boolean value indicating whether the same number of doctors should be scheduled for each night during the scheduling period.
- `num_doctors`: An optional integer indicating the number of doctors to schedule each night if `same_num_doctors` is set to `true`.
- `num_doctors_per_night`: An optional dictionary indicating the number of doctors to schedule for each night during the scheduling period. The keys of the dictionary should be dates in the format `YYYY-MM-DD` and the values should be integers.
- `holiday_days`: An optional comma-separated string of dates in the format `YYYY-MM-DD` indicating which days are holidays.
- `find`: An integer indicating the number of optimal schedules to find.

### Response Body

The response body is a JSON object with the following fields:

- `schedule`: A dictionary representing the generated schedule. The keys of the dictionary are dates in the format `YYYY-MM-DD` and the values are lists of tuples representing the doctors assigned to each shift on that day. Each tuple contains the name of the doctor and the number of points earned for that shift.
- `num_shifts`: A dictionary indicating the number of shifts assigned to each doctor.
- `num_weekend_shifts`: A dictionary indicating the number of weekend shifts assigned to each doctor.
- `points`: A dictionary indicating the number of points earned by each doctor.

## Implementation Details

The implementation of the scheduling logic is based on the following steps:

1. Parse the input parameters from the request body.
2. Calculate the points for each day based on whether it is a holiday, a Saturday, or a Sunday.
3. Generate a list of days in the scheduling period.
4. For each day, choose doctors such that each doctor is assigned an equal number of shifts.
5. Calculate the maximum and minimum points earned by the doctors.
6. Calculate the difference in points between the doctors.
7. Find the optimal schedules by minimizing the difference in points, the difference in the number of shifts assigned to each doctor, and the variance in the spacing of shifts between doctors.
8. Group the schedule by day and convert the datetime to a string.
9. Return the result as a JSON response.

## Examples

### Example Request

```
{
    "doctor_names": "John,Paul,Ringo,George",
    "start_date": "2022-01-01",
    "end_date": "2022-01-31",
    "same_num_doctors": "Y",
    "num_doctors": 2,
    "holiday_days": "2022-01-01,2022-01-02",
    "find": 1
}

```

### Example Response

```
{
    "schedule": {
        "2022-01-01": [
            {
                "doctor": "John",
                "points": 2
            },
            {
                "doctor": "Paul",
                "points": 2
            }
        ],
        "2022-01-02": [
            {
                "doctor": "Ringo",
                "points": 2
            },
            {
                "doctor": "George",
                "points": 2
            }
        ],
        "2022-01-03": [
            {
                "doctor": "John",
                "points": 1
            },
            {
                "doctor": "Paul",
                "points": 1
            }
        ],
        ...
    },
    "num_shifts": {
        "John": 12,
        "Paul": 12,
        "Ringo": 12,
        "George": 12
    },
    "num_weekend_shifts": {
        "John": 2,
        "Paul": 2,
        "Ringo": 2,
        "George": 2
    },
    "points": {
        "John": 22,
        "Paul": 22,
        "Ringo": 22,
        "George": 22
    }
}

```