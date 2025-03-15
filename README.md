# ha-fitbit-extra

_Add extra Fitbit data to Home Assistant._

The [official Fitbit integration](https://www.home-assistant.io/integrations/fitbit/) doesn't pull all data. This is a
quick-and-dirty service to send that missing data to Home Assistant.

It runs on an external server (not on Home Assistant as an integration) since you have to fiddle with OAuth2 callbacks.

Unfortunately, there is no way to backfill historical data due to HA's timeseries architecture. This
sensor is dependent on how often your Fitbit app syncs. The Fitbit API can return data in 1 second intervals but data
may not be synced by the app for long periods of time. There isn't an easy solution for this. You may want to allow the
app to run unrestricted in background.

**Added Sensors:**

- Heart Rate (BPM).

## Install

1. Create a venv on your local desktop machine and on your server.
2. Do `pip install -r requirements.txt` on both venvs.
3. Set up a Fitbit developer account according to these
   instructions: <https://www.home-assistant.io/integrations/fitbit/>
4. On your local desktop machine, run `./authorize.py <client_id>` where `<client_id>` is your OAuth 2.0 Client ID
   from <https://dev.fitbit.com/apps>. Complete the authorization in your browser.
5. Copy the output JSON.
6. On your server, run `./import-auth.py` and paste your JSON.
7. Add and enable the `fitbit-extra.service` (make sure to enter your environment variables in
   `/etc/secrets/fitbit-extra`).
8. Add this to your Home Assistant MQTT config:
   ```yaml
   - name: "Fitbit Heart Rate"
     state_topic: "fitbit-extra/fitbit-extra-heart-rate"
     state_class: measurement
     unique_id: fitbit_extra_heart_rate
     unit_of_measurement: "BPM"
   ```

If you have multiple Fitbit accounts on your HA, use `main.py --person-name <person_name>` and update `unique_id` and
`state_topic` accordingly.
