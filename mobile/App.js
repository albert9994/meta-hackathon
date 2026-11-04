import React, { useState, useEffect, useCallback } from 'react';
import {
  StyleSheet,
  View,
  Text,
  TouchableOpacity,
  SafeAreaView,
  StatusBar,
  Modal,
  Platform,
  Alert,
} from 'react-native';

import VibeMapView from './components/MapView';
import SearchHUD from './components/SearchHUD';
import VisionAuditModal from './components/VisionAuditModal';
import EndRideModal from './components/EndRideModal';
import Leaderboard from './components/Leaderboard';
import { planRoute, API_BASE_URL } from './utils/api';

export default function App() {
  // Stări pentru navigare și traseu
  const [currentPlan, setCurrentPlan] = useState(null);
  const [routeGeojson, setRouteGeojson] = useState(null);
  const [hazards, setHazards] = useState([]);
  const [isLoadingRoute, setIsLoadingRoute] = useState(false);

  // Stări pentru modalele Dev 3
  const [visionOpen, setVisionOpen] = useState(false);
  const [endRideOpen, setEndRideOpen] = useState(false);
  const [leaderboardOpen, setLeaderboardOpen] = useState(false);
  const [lastAlert, setLastAlert] = useState(null);

  // Date demonstrative pentru sumarul cursei (EndRideModal)
  const [ridePayload, setRidePayload] = useState({
    stats: { distance_km: 7.8, duration_min: 26, avg_speed_kmh: 18.0 },
    recap_text: "Smooth cruise along Dâmbovița riverbanks and through Cotroceni with 80% tree shade.",
    quiz: {
      question: "Which road surface offers the highest micro-mobility grip while turning?",
      options: ["Smooth Asphalt", "Wet Cobblestones", "Loose Gravel", "Tram Track Steel"],
      correct_index: 0,
      fun_fact: "Dedicated cycling asphalt surfaces reduce vibration fatigue by over 35%."
    },
    badge: {
      title: "🌿 Canopy Glider",
      lore: "Maintained optimal pace through shaded micro-routes in Bucharest."
    }
  });

  // Încarcă pericolele raportate din backend SQLite la pornire
  const fetchHazards = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/hazards`);
      if (res.ok) {
        const data = await res.json();
        const list = Array.isArray(data) ? data : data?.hazards;
        setHazards(Array.isArray(list) ? list : []);
      }
    } catch (err) {
      console.log("Could not fetch hazards:", err.message);
    }
  }, []);

  useEffect(() => {
    fetchHazards();
  }, [fetchHazards]);

  // Planificare rută prin SearchHUD către backend-ul AI
  const handleRouteSearch = async (searchData) => {
    const userPrompt = (
      typeof searchData === 'string'
        ? searchData
        : searchData?.user_prompt || searchData?.prompt || ''
    ).trim();
    if (!userPrompt) return;

    setIsLoadingRoute(true);
    try {
      const res = await planRoute({
        user_prompt: userPrompt,
        vibe_preset: searchData?.vibe_preset || 'green_shady',
        city: searchData?.city,
      });
      // planRoute (api.js) garantează geojson valid și aruncă ApiError altfel
      setCurrentPlan(res.vibe_plan);
      setRouteGeojson(res.geojson);
    } catch (error) {
      console.log('Error planning route:', error);
      Alert.alert('Route planning failed', error?.message || 'Unknown error');
    } finally {
      setIsLoadingRoute(false);
    }
  };

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" />

      {/* 1. HARTA PE TOT ECRANUL (Background complet) */}
      <View style={StyleSheet.absoluteFillObject}>
        <VibeMapView
          plan={currentPlan}
          geojson={routeGeojson}
          hazards={hazards}
          style={StyleSheet.absoluteFillObject}
        />
      </View>

      {/* 2. HUD DE CĂUTARE ȘI VIBE-URI (Plutitor sus) */}
      <SafeAreaView style={styles.topSafeArea} pointerEvents="box-none">
        <View style={styles.searchWrapper}>
          <SearchHUD
            onSearchSubmit={handleRouteSearch}
            onPlanSelected={(p) => {
              setCurrentPlan(p);
              setRouteGeojson(null); // evită polyline vechi cu markeri noi
            }}
            isLoading={isLoadingRoute}
          />
        </View>

        {/* Notificare audio plutitoare dacă camera detectează un pericol */}
        {lastAlert && (
          <TouchableOpacity
            style={styles.floatingAlert}
            activeOpacity={0.9}
            onPress={() => setLastAlert(null)}
          >
            <Text style={styles.floatingAlertTitle}>🔊 AI In-Ear Co-Pilot</Text>
            <Text style={styles.floatingAlertText}>{lastAlert}</Text>
          </TouchableOpacity>
        )}
      </SafeAreaView>

      {/* 3. DOCK PLUTITOR DE CONTROL (Plutitor jos) */}
      <SafeAreaView style={styles.bottomSafeArea} pointerEvents="box-none">
        <View style={styles.bottomDock}>
          <TouchableOpacity
            style={[styles.dockBtn, styles.cameraBtn]}
            onPress={() => setVisionOpen(true)}
            activeOpacity={0.8}
          >
            <Text style={styles.dockBtnIcon}>📷</Text>
            <Text style={styles.dockBtnLabel}>Audit Road</Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={[styles.dockBtn, styles.finishBtn]}
            onPress={() => setEndRideOpen(true)}
            activeOpacity={0.8}
          >
            <Text style={styles.dockBtnIcon}>🏁</Text>
            <Text style={styles.dockBtnLabel}>End Ride</Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={[styles.dockBtn, styles.leaderboardBtn]}
            onPress={() => setLeaderboardOpen(true)}
            activeOpacity={0.8}
          >
            <Text style={styles.dockBtnIcon}>🏆</Text>
            <Text style={styles.dockBtnLabel}>Rankings</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>

      {/* 4. MODAL CLASAMENT (Leaderboard) */}
      <Modal
        visible={leaderboardOpen}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setLeaderboardOpen(false)}
      >
        <View style={styles.modalLeaderboardContainer}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>Crew Leaderboard</Text>
            <TouchableOpacity
              style={styles.closeBtn}
              onPress={() => setLeaderboardOpen(false)}
            >
              <Text style={styles.closeBtnText}>Done</Text>
            </TouchableOpacity>
          </View>
          <Leaderboard crewCode="COTROCENI-GANG" />
        </View>
      </Modal>

      {/* 5. MODAL AUDIT VIZUAL STRADAL (Camera & Vision Agent) */}
      <VisionAuditModal
        visible={visionOpen}
        onClose={() => {
          setVisionOpen(false);
          fetchHazards(); // Reîncarcă pericolele proaspăt salvate pe hartă
        }}
        onAudioAlertTriggered={(cue) => setLastAlert(cue)}
      />

      {/* 6. MODAL FINAL DE CURSĂ (Quiz, Insignă & Feed Post) */}
      <EndRideModal
        visible={endRideOpen}
        rideData={ridePayload}
        onClose={() => setEndRideOpen(false)}
        onPostSuccess={() => {
          setEndRideOpen(false);
          alert("Ride recap posted to the community feed!");
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0E1118',
  },
  topSafeArea: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    zIndex: 10,
  },
  searchWrapper: {
    paddingHorizontal: 14,
    paddingTop: Platform.OS === 'android' ? 30 : 6,
  },
  floatingAlert: {
    marginHorizontal: 16,
    marginTop: 10,
    backgroundColor: 'rgba(20, 24, 33, 0.95)',
    borderLeftWidth: 4,
    borderLeftColor: '#fc5200',
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRadius: 12,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.35,
    shadowRadius: 8,
    elevation: 6,
  },
  floatingAlertTitle: {
    color: '#fc5200',
    fontSize: 12,
    fontWeight: '800',
    textTransform: 'uppercase',
  },
  floatingAlertText: {
    color: '#FFF',
    fontSize: 13,
    fontWeight: '500',
    marginTop: 2,
  },
  bottomSafeArea: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    zIndex: 10,
  },
  bottomDock: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    backgroundColor: 'rgba(14, 17, 24, 0.92)',
    marginHorizontal: 16,
    marginBottom: Platform.OS === 'ios' ? 10 : 20,
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.08)',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.45,
    shadowRadius: 12,
    elevation: 10,
  },
  dockBtn: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 8,
    marginHorizontal: 4,
    borderRadius: 14,
  },
  cameraBtn: {
    backgroundColor: '#fc5200',
  },
  finishBtn: {
    backgroundColor: '#1E2330',
    borderWidth: 1,
    borderColor: 'rgba(255, 255, 255, 0.1)',
  },
  leaderboardBtn: {
    backgroundColor: '#161A24',
    borderWidth: 1,
    borderColor: 'rgba(252, 82, 0, 0.4)',
  },
  dockBtnIcon: {
    fontSize: 18,
    marginBottom: 2,
  },
  dockBtnLabel: {
    color: '#FFF',
    fontSize: 12,
    fontWeight: '700',
  },
  modalLeaderboardContainer: {
    flex: 1,
    backgroundColor: '#0E1118',
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 20,
    paddingBottom: 14,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255, 255, 255, 0.08)',
  },
  modalTitle: {
    color: '#FFF',
    fontSize: 18,
    fontWeight: '800',
  },
  closeBtn: {
    backgroundColor: '#1E2330',
    paddingVertical: 6,
    paddingHorizontal: 14,
    borderRadius: 12,
  },
  closeBtnText: {
    color: '#fc5200',
    fontSize: 14,
    fontWeight: '700',
  },
});