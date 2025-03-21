# ha-fitbit-extra

_Add extra Fitbit data to Home Assistant._

The [official Fitbit integration](https://www.home-assistant.io/integrations/fitbit/) doesn't pull all data. This is a
quick-and-dirty service to send that missing data to Home Assistant.

It runs on an external server (not on Home Assistant as an integration) since you have to fiddle with OAuth2 callbacks.

Unfortunately, there is no way to backfill historical data due to HA's timeseries architecture. This
sensor is dependent on how often your Fitbit app syncs. The Fitbit API can return data in 1 second intervals but data
may not be synced by the app for long periods of time. There isn't an easy solution for this. You may want to allow the
app to run unrestricted in background.

The app seems to sync at least every 30 minutes. Although it isn't real-time, letting Fitbit handle syncing is more
battery efficient than making the HA WearOS app sync often.

**Added Sensors:**

- Heart Rate (BPM).

## Install

1. Create a venv on your local desktop machine and on your server.
2. Do `pip install -r requirements.txt` on both venvs.
3. Set up a Fitbit developer account according to these
   instructions: <https://www.home-assistant.io/integrations/fitbit/>
4. Set the `Redirect URL` to `https://localhost:5000/callback`
5. On your local desktop machine, run `./authorize.py <client_id>` where `<client_id>` is your OAuth 2.0 Client ID
   from <https://dev.fitbit.com/apps>. Complete the authorization in your browser. If nothing happens after clicking the
   `Allow` button, check the request console for a GET to `https://localhost:5000/callback?code=` and open that URL in a
   new tab to complete the request (this may happen due to browsers not trusting self-signed SSL certs completely).
6. Copy the output JSON.
7. On your server, run `./import-auth.py` and paste your JSON.
8. Add and enable the `fitbit-extra.service` (make sure to enter your environment variables in
   `/etc/secrets/fitbit-extra`).
9. Add this to your Home Assistant MQTT config:
   ```yaml
   - name: "Fitbit Heart Rate"
     state_topic: "fitbit-extra/fitbit-extra-heart-rate"
     state_class: measurement
     unique_id: fitbit_extra_heart_rate
     unit_of_measurement: "BPM"
   ```

If you have multiple Fitbit accounts on your HA, use `main.py --person-name <person_name>` and update `unique_id` and
`state_topic` accordingly.
