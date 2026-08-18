using Meta.XR.MRUtilityKit;
using UnityEngine;

namespace EnchantedNightGarden
{
    /// <summary>
    /// Small head-locked readout. You will learn more from this than from any
    /// screenshot, because every Phase 1 success criterion is a number on it.
    ///
    /// Reports: frame time, anchor count, drift since session start, and the
    /// label dump from the room scan (UNKNOWNS.md Test #3 -- what did Space Setup
    /// actually call your desk?).
    ///
    /// Also answers Test #2b: open the Mixed Reality Link window and watch whether
    /// GPU frame time moves. If it costs 1-2ms, that comes out of the art budget
    /// and we should know now rather than in Phase 3.
    /// </summary>
    public class DebugOverlay : MonoBehaviour
    {
        [SerializeField] private GardenBootstrap _bootstrap;
        [SerializeField] private AnchorPlanter _planter;
        [SerializeField] private RoomWireframe _wireframe;
        [SerializeField] private TextMesh _text;

        [Header("Placement")]
        [SerializeField] private float _distance = 0.75f;
        [SerializeField] private Vector2 _offset = new(-0.25f, -0.2f);
        [SerializeField] private OVRInput.RawButton _toggleButton = OVRInput.RawButton.LThumbstick;

        private float _smoothedFrameMs;
        private int _anchorCount;
        private bool _visible = true;
        private bool _showLabels;

        public void OnRoomReady(MRUKRoom room)
        {
            _anchorCount = room.Anchors.Count;
        }

        private void Update()
        {
            if (OVRInput.GetDown(_toggleButton))
            {
                // First press expands to the full label dump, second hides entirely.
                if (_visible && !_showLabels) _showLabels = true;
                else if (_visible) { _visible = false; _showLabels = false; }
                else _visible = true;
            }

            if (_text != null) _text.gameObject.SetActive(_visible);
            if (!_visible || _text == null) return;

            FollowHead();

            float frameMs = Time.unscaledDeltaTime * 1000f;
            _smoothedFrameMs = Mathf.Lerp(_smoothedFrameMs, frameMs, 0.1f);

            _text.text = BuildReport();
        }

        private void FollowHead()
        {
            if (Camera.main == null) return;

            Transform cam = Camera.main.transform;
            Vector3 pos = cam.position
                          + cam.forward * _distance
                          + cam.right * _offset.x
                          + cam.up * _offset.y;

            _text.transform.SetPositionAndRotation(pos, Quaternion.LookRotation(pos - cam.position));
        }

        private string BuildReport()
        {
            float fps = _smoothedFrameMs > 0.01f ? 1000f / _smoothedFrameMs : 0f;

            string drift = "n/a";
            if (_planter != null && _planter.HasFlower)
            {
                float cm = Vector3.Distance(
                    _planter.FlowerPosition, _planter.FlowerPositionAtSessionStart) * 100f;
                drift = $"{cm:F1} cm";
            }

            string report =
                $"frame  {_smoothedFrameMs:F1} ms  ({fps:F0} fps)\n" +
                $"room   {(_bootstrap != null && _bootstrap.RoomReady ? "loaded" : "WAITING")}\n" +
                $"anchors {_anchorCount}\n" +
                $"drift  {drift}\n" +
                $"intens {(_bootstrap != null ? _bootstrap.Intensity : 0f):F2}";

            if (_showLabels && _wireframe != null)
            {
                report += "\n\n" + _wireframe.LabelReport;
            }

            return report;
        }
    }
}
