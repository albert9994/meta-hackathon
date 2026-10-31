import React, { useState } from 'react';
import { StyleSheet, View, Text, TouchableOpacity, SafeAreaView, StatusBar, ScrollView } from 'react-native';

import SearchHUD from './components/SearchHUD';
import VisionAuditModal from './components/VisionAuditModal';
import EndRideModal from './components/EndRideModal';
import Leaderboard from './components/Leaderboard';

const BACKEND_URL = process.env.EXPO_PUBLIC_BACKEND_URL || 'http://localhost:8000';

export default function App() {
  const [visionOpen, setVisionOpen] = useState(false);
  const [endRideOpen, setEndRideOpen] = useState(false);
  const [activeTab, setActiveTab] = useState('hub');
  const [lastAlert, setLastAlert] = useState(null);

  const mockRidePayload = {
    stats: { distance_km: 6.4, duration_min: 24, avg_speed_kmh: 16.0 },
    recap_text: "You avoided busy boulevards entirely. 6.4 km of quiet cruising through Cotroceni without acoustic stress.",
    quiz: {
      question: "Which historic quarter did you ride through to bypass boulevard traffic?",
      options: ["Cotroceni Quarter", "Unirii Boulevard", "Pipera Industrial Area"],
      correct_index: 0,
      fun_fact: "Residential streets in Cotroceni feature 40% less ambient noise compared to main arteries."
    },
    badge: {
      title: "🌿 The Shade Cartographer",
      lore: "Navigated under tree canopy cover for 85% of your route."
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" />

      {activeTab === 'hub' ? (
        <View style={styles.inner}>
          <SearchHUD 
            onSearchSubmit={(data) => alert(`Search submitted: ${data.user_prompt}`)} 
            isLoading={false} 
          />

          <ScrollView contentContainerStyle={styles.centerCard}>
            <Text style={styles.title}>VibeRide Dev 3 Hub</Text>
            <Text style={styles.subtitle}>Target API: {BACKEND_URL}</Text>

            {lastAlert && (
              <View style={styles.alertCard}>
                <Text style={styles.alertTitle}>Incoming Audio Alert:</Text>
                <Text style={styles.alertText}>{lastAlert}</Text>
              </View>
            )}

            <View style={styles.menuGroup}>
              <TouchableOpacity style={styles.primaryBtn} onPress={() => setVisionOpen(true)}>
                <Text style={styles.btnText}>📷 Test Camera / Street Audit</Text>
              </TouchableOpacity>

              <TouchableOpacity style={styles.secondaryBtn} onPress={() => setEndRideOpen(true)}>
                <Text style={styles.btnText}>🏁 Test Ride Summary (Quiz & Badge)</Text>
              </TouchableOpacity>

              <TouchableOpacity style={styles.navBtn} onPress={() => setActiveTab('leaderboard')}>
                <Text style={styles.btnText}>🏆 Open Crew Leaderboard</Text>
              </TouchableOpacity>
            </View>
          </ScrollView>
        </View>
      ) : (
        <View style={styles.fullScreen}>
          <TouchableOpacity style={styles.backBtn} onPress={() => setActiveTab('hub')}>
            <Text style={styles.backBtnText}>← Back to Hub</Text>
          </TouchableOpacity>
          <Leaderboard crewCode="COTROCENI-GANG" />
        </View>
      )}

      <VisionAuditModal
        visible={visionOpen}
        onClose={() => setVisionOpen(false)}
        onAudioAlertTriggered={(cue) => setLastAlert(cue)}
      />

      <EndRideModal
        visible={endRideOpen}
        rideData={mockRidePayload}
        onClose={() => setEndRideOpen(false)}
        onPostSuccess={() => alert("Ride successfully posted to the crew feed!")}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0E1118' },
  inner: { flex: 1 },
  centerCard: { marginTop: 140, padding: 20, alignItems: 'center' },
  title: { fontSize: 24, fontWeight: '800', color: '#FFF' },
  subtitle: { fontSize: 13, color: '#7E8A9A', marginTop: 4, marginBottom: 24 },
  alertCard: { backgroundColor: 'rgba(252, 82, 0, 0.15)', borderWidth: 1, borderColor: '#fc5200', padding: 14, borderRadius: 12, width: '100%', marginBottom: 20 },
  alertTitle: { color: '#fc5200', fontWeight: '700', fontSize: 13 },
  alertText: { color: '#FFF', marginTop: 4, fontSize: 14 },
  menuGroup: { width: '100%', gap: 14 },
  primaryBtn: { backgroundColor: '#fc5200', paddingVertical: 16, borderRadius: 14, alignItems: 'center' },
  secondaryBtn: { backgroundColor: '#1E2330', borderWidth: 1, borderColor: '#3B4254', paddingVertical: 16, borderRadius: 14, alignItems: 'center' },
  navBtn: { backgroundColor: '#161A24', borderWidth: 1, borderColor: '#fc5200', paddingVertical: 16, borderRadius: 14, alignItems: 'center' },
  btnText: { color: '#FFF', fontWeight: '700', fontSize: 15 },
  fullScreen: { flex: 1 },
  backBtn: { backgroundColor: '#1E2330', padding: 14, marginHorizontal: 16, marginTop: 10, borderRadius: 12, alignItems: 'center' },
  backBtnText: { color: '#fc5200', fontWeight: '700', fontSize: 14 }
});