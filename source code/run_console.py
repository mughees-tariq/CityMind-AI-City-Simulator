from simulation.simulator import CityMindSimulator


def main():
    # Execute full simulation pipeline and forward tick loop.
    sim = CityMindSimulator()
    sim.runFullSimulation()


if __name__ == "__main__":
    main()