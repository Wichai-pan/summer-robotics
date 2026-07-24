import cv2

from ultralytics import YOLO

# Function to list available camera indices
def list_cameras(max_index=5):
    available = []
    for idx in range(max_index):
        cap = cv2.VideoCapture(idx)
        if cap.isOpened():
            available.append(idx)
            cap.release()
    return available

# List available cameras and prompt user to select one
cameras = list_cameras()
if not cameras:
    print("No cameras found.")
    exit(1)
print(f"Available cameras: {cameras}")
selected = int(input(f"Select camera index from {cameras}: "))

# Load the YOLO11 model
model = YOLO("yolo11n.pt")

# Open the selected camera
cap = cv2.VideoCapture(selected)

# Loop through the video frames
while cap.isOpened():
    # Read a frame from the camera
    success, frame = cap.read()

    if success:
        # Run YOLO11 tracking on the frame, persisting tracks between frames
        results = model.track(frame, persist=True)

        # Visualize the results on the frame
        annotated_frame = results[0].plot()

        # Display the annotated frame in a window
        cv2.imshow("YOLO11 Live", annotated_frame)

        # Break the loop if 'q' is pressed
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
    else:
        # Break the loop if the camera is not providing frames
        break

# Release the video capture object and close the display window
cap.release()
cv2.destroyAllWindows()
