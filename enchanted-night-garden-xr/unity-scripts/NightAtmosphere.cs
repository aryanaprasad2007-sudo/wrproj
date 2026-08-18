using UnityEngine;

namespace EnchantedNightGarden
{
    /// <summary>
    /// Owns passthrough appearance: the nighttime Color LUT and its weight.
    ///
    /// This is the entire visual conceit of the project under test (UNKNOWNS.md
    /// Test #5). The LUT is bound to a button so you can A/B it honestly -- the
    /// effect is much easier to overrate when you cannot switch it off.
    ///
    /// Remember what a LUT is and is not: it remaps the colours already in the
    /// camera image. It cannot light your real bedspread with virtual moonlight.
    /// If the room reads as "dark noisy room" rather than "moonlit garden", that
    /// is the finding, and it changes the art direction before Phase 3.
    /// </summary>
    [RequireComponent(typeof(OVRPassthroughLayer))]
    public class NightAtmosphere : MonoBehaviour
    {
        [Header("LUT")]
        [Tooltip("Texture2D LUT. Import settings: compression None, sRGB off, no mipmaps.")]
        [SerializeField] private Texture2D _nightLut;
        [SerializeField] private bool _flipY;

        [Range(0f, 1f)]
        [Tooltip("How strongly the LUT is applied. Tune this live -- subtle usually wins.")]
        [SerializeField] private float _lutWeight = 0.85f;

        [Header("Controls")]
        [SerializeField] private OVRInput.RawButton _toggleButton = OVRInput.RawButton.A;

        private OVRPassthroughLayer _layer;
        private OVRPassthroughColorLut _lut;
        private bool _lutEnabled = true;
        private float _intensity = 1f;

        private void Awake()
        {
            _layer = GetComponent<OVRPassthroughLayer>();

            if (_nightLut == null)
            {
                Debug.LogWarning("[Garden] No night LUT assigned. Passthrough will be untinted.");
                return;
            }

            _lut = new OVRPassthroughColorLut(_nightLut, _flipY);
            ApplyLut();
        }

        private void Update()
        {
            if (OVRInput.GetDown(_toggleButton))
            {
                _lutEnabled = !_lutEnabled;
                ApplyLut();
                Debug.Log($"[Garden] Night LUT {(_lutEnabled ? "ON" : "OFF")}");
            }
        }

        /// <summary>Called by GardenBootstrap. Panic fade pulls the tint out with everything else.</summary>
        public void ApplyIntensity(float intensity)
        {
            if (Mathf.Approximately(_intensity, intensity)) return;
            _intensity = intensity;
            ApplyLut();
        }

        private void ApplyLut()
        {
            if (_lut == null || _layer == null) return;

            if (_lutEnabled)
            {
                _layer.SetColorLut(_lut, _lutWeight * _intensity);
            }
            else
            {
                // No ClearColorLut in this SDK -- DisableColorMap turns off all
                // passthrough colour styling, LUT included.
                _layer.DisableColorMap();
            }
        }

        private void OnValidate()
        {
            if (Application.isPlaying) ApplyLut();
        }
    }
}
