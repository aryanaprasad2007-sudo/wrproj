using System.Collections;
using Meta.XR.MRUtilityKit;
using UnityEngine;

namespace EnchantedNightGarden
{
    /// <summary>
    /// Phase 1 entry point. Waits for MRUK to load the room scan, then hands the
    /// room to everything that needs it. Also owns the global intensity value and
    /// the panic fade.
    ///
    /// Global intensity is deliberately here and nowhere else. Every visual system
    /// scales against it, which is what gives us the panic fade, the calm-down
    /// behaviour and future preset transitions for free rather than as three
    /// separate mechanisms.
    /// </summary>
    public class GardenBootstrap : MonoBehaviour
    {
        [Header("Systems")]
        [SerializeField] private RoomWireframe _wireframe;
        [SerializeField] private NightAtmosphere _atmosphere;
        [SerializeField] private AnchorPlanter _planter;
        [SerializeField] private SafetyPolicy _safety;
        [SerializeField] private DebugOverlay _overlay;

        [Header("Panic fade")]
        [Tooltip("Hold to drop all virtual content to near-zero opacity.")]
        [SerializeField] private OVRInput.RawButton _panicButton = OVRInput.RawButton.B;
        [SerializeField] private float _panicFadeSeconds = 0.25f;

        /// <summary>0 = plain passthrough, 1 = full garden. Everything visual scales against this.</summary>
        public float Intensity { get; private set; } = 1f;

        public bool RoomReady { get; private set; }
        public MRUKRoom Room { get; private set; }

        private float _targetIntensity = 1f;

        private void Start()
        {
            // Panic fade must work before the room loads. If the scan fails or MRUK
            // hangs, the user is still wearing a headset and still needs an out.
            StartCoroutine(WaitForRoom());
        }

        private IEnumerator WaitForRoom()
        {
            if (MRUK.Instance == null)
            {
                Debug.LogError("[Garden] No MRUK instance in scene. Add the MRUK prefab.");
                yield break;
            }

            MRUK.Instance.RegisterSceneLoadedCallback(OnSceneLoaded);

            // MRUK's scene load is async and can fail silently if the headset has no
            // Space Setup for the current room. Surface that rather than hanging.
            float timeout = 15f;
            while (!RoomReady && timeout > 0f)
            {
                timeout -= Time.deltaTime;
                yield return null;
            }

            if (!RoomReady)
            {
                Debug.LogError("[Garden] MRUK loaded no room within 15s. " +
                               "Run Space Setup on the headset (Settings > Physical space).");
            }
        }

        private void OnSceneLoaded()
        {
            Room = MRUK.Instance.GetCurrentRoom();
            if (Room == null)
            {
                Debug.LogError("[Garden] Scene loaded but GetCurrentRoom() is null.");
                return;
            }

            RoomReady = true;
            Debug.Log($"[Garden] Room loaded with {Room.Anchors.Count} anchors.");

            _safety?.BuildFromRoom(Room);
            _wireframe?.BuildFromRoom(Room);
            _planter?.OnRoomReady(Room);
            _overlay?.OnRoomReady(Room);
        }

        private void Update()
        {
            bool panicking = OVRInput.Get(_panicButton);
            _targetIntensity = panicking ? 0f : 1f;

            Intensity = Mathf.MoveTowards(
                Intensity, _targetIntensity, Time.deltaTime / Mathf.Max(_panicFadeSeconds, 0.01f));

            _atmosphere?.ApplyIntensity(Intensity);
            _wireframe?.ApplyIntensity(Intensity);
            _planter?.ApplyIntensity(Intensity);
        }
    }
}
