1) The filter UI is populated with a Advanced entry, when I switch tab, it's not populating the basic equivalent automatically. 
2) Same as above, when we switch from a pre-filled filter from Advanced to basic, back to advanced the query vanishes. 
3) Show inline errors on the fly, rather than when saving the pipeline. Use zod for validations in the frontend
4) Should not add same source twice to the same pipeline
5) Change the UI such that, we have the preview of data on the right and pipeline builder on the left of the screen, where the sections for Filter, Sort, Pivot, Map, Lookup are all populated and scrollable
6) Dry run should happen whenever there is a change in the pipeline automatically, for the newly changed spec
7) After applying aggregate, I should be able to filter based on the aggregated columns eg., `total_amount > 200`. Similarly Pivot.
8) If there is a date field, we should be able to aggregate by Day of week, Month, year, date etc.,
9)
