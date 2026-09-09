"""
Guided load-cell calibration.

Run this standalone (not through the GUI) whenever you need to
(re)calibrate -- e.g. first setup, or after moving/reinstalling the
load cell.

    python3 calibrate.py

Follow the prompts. Saves tare_offset and calibration_factor to
calibration.json, which hx711_sensor.py automatically loads on startup.
"""

from hx711_sensor import HX711


def main():
    print("=" * 60)
    print("HX711 Load Cell Calibration")
    print("=" * 60)

    hx = HX711()

    input("\nStep 1: Make sure the load cell is EMPTY, then press Enter...")
    print("Taring...")
    offset = hx.tare(times=20)
    if offset is None:
        print("ERROR: Could not get a stable reading. Check wiring and try again.")
        hx.close()
        return
    print(f"Tare offset recorded: {offset:.1f}")

    print(
        "\nStep 2: Place a known weight on the load cell.\n"
        "         (e.g. a sealed food item with printed weight, or\n"
        "         anything you've weighed on a separate kitchen scale)"
    )
    while True:
        raw_input_val = input(
            "Enter the known weight in GRAMS (e.g. 500), or 'q' to quit: "
        ).strip()
        if raw_input_val.lower() == "q":
            hx.close()
            return
        try:
            known_weight = float(raw_input_val)
            if known_weight <= 0:
                print("Weight must be a positive number.")
                continue
            break
        except ValueError:
            print("Please enter a valid number.")

    input("Confirm the weight is resting steadily on the load cell, then press Enter...")
    print("Reading...")
    factor = hx.calibrate(known_weight_grams=known_weight, times=20)

    if factor is None:
        print(
            "ERROR: Could not compute calibration -- reading was unstable or "
            "identical to tare (no weight detected). Try again."
        )
        hx.close()
        return

    print(f"\nCalibration factor computed: {factor:.4f}")
    print("Saved to calibration.json -- this will be used automatically from now on.")

    print("\nStep 3: Verification. Remove the weight to confirm it reads ~0g.")
    input("Press Enter once the load cell is empty again...")
    verify_raw = hx.read_average(times=10)
    if verify_raw is None:
        print("Could not get a stable reading just now -- skipping this check.")
    else:
        grams = (verify_raw - hx.tare_offset) / hx.calibration_factor
        print(f"Current reading: {grams:.1f} g (should be close to 0)")

    print(
        "\nStep 4 (optional): Place the same known weight back on to verify "
        f"it now reads close to {known_weight:.1f} g."
    )
    input("Press Enter once the known weight is back on the load cell (or Ctrl+C to skip)...")
    try:
        verify_raw = hx.read_average(times=10)
        if verify_raw is None:
            print("Could not get a stable reading just now -- skipping this check.")
        else:
            grams = (verify_raw - hx.tare_offset) / hx.calibration_factor
            print(f"Current reading: {grams:.1f} g (should be close to {known_weight:.1f} g)")
    except KeyboardInterrupt:
        pass

    print("\nCalibration complete.")
    hx.close()


if __name__ == "__main__":
    main()
