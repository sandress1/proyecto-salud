
DROP TABLE IF EXISTS feedback_pqrs CASCADE;
DROP TABLE IF EXISTS chat_sessions CASCADE;
DROP TABLE IF EXISTS appointments CASCADE;
DROP TABLE IF EXISTS slots CASCADE;
DROP TABLE IF EXISTS doctors CASCADE;
DROP TABLE IF EXISTS specialties CASCADE;
DROP TABLE IF EXISTS patients CASCADE;


CREATE TABLE patients (
    id SERIAL PRIMARY KEY,
    full_name VARCHAR(120) NOT NULL,
    personal_id VARCHAR(30) UNIQUE NOT NULL,
    birth_date DATE NOT NULL,
    phone VARCHAR(30),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE specialties (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE doctors (
    id SERIAL PRIMARY KEY,
    full_name VARCHAR(120) NOT NULL,
    specialty_id INTEGER NOT NULL REFERENCES specialties(id),
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE slots (
    id SERIAL PRIMARY KEY,
    doctor_id INTEGER NOT NULL REFERENCES doctors(id),
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    is_available BOOLEAN DEFAULT TRUE
);

CREATE TABLE appointments (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    doctor_id INTEGER NOT NULL REFERENCES doctors(id),
    slot_id INTEGER NOT NULL REFERENCES slots(id),
    status VARCHAR(20) DEFAULT 'booked',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE chat_sessions (
    id SERIAL PRIMARY KEY,
    whatsapp_number VARCHAR(50) UNIQUE NOT NULL,
    current_step VARCHAR(100),
    selected_option VARCHAR(50),
    patient_id INTEGER REFERENCES patients(id),
    temp_data JSONB DEFAULT '{}'::jsonb,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE feedback_pqrs (
    id SERIAL PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    feedback_type VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


INSERT INTO patients (full_name, personal_id, birth_date, phone) VALUES
('Laura Gómez', '1001', '1995-04-12', '3001111111'),
('Carlos Pérez', '1002', '1988-09-25', '3002222222'),
('María Rodríguez', '1003', '2000-01-18', '3003333333'),
('Andrés Martínez', '1004', '1979-11-03', '3004444444'),
('Sofía Ramírez', '1005', '1992-07-30', '3005555555'),
('Juan López', '1006', '1985-03-14', '3006666666'),
('Valentina Torres', '1007', '1998-12-05', '3007777777'),
('Camila Herrera', '1008', '1990-06-21', '3008888888'),
('Miguel Castro', '1009', '1975-10-10', '3009999999'),
('Daniela Morales', '1010', '2002-02-28', '3011111111');

INSERT INTO specialties (name) VALUES
('Medicina General'),
('Pediatría'),
('Odontología'),
('Ginecología'),
('Dermatología'),
('Psicología'),
('Cardiología'),
('Nutrición'),
('Fisioterapia');

INSERT INTO doctors (full_name, specialty_id) VALUES
('Dra. Ana Pérez', 1),
('Dr. Luis Gómez', 1),
('Dra. Carolina Ruiz', 2),
('Dr. Miguel Torres', 2),
('Dra. Daniela Castro', 3),
('Dra. Marcela Henao', 4),
('Dr. Ricardo Salazar', 5),
('Dra. Paula Restrepo', 6),
('Dr. Jorge Molina', 7),
('Dra. Isabel Cano', 8),
('Dr. Sebastián Mejía', 9);


INSERT INTO slots (doctor_id, start_time, end_time, is_available) VALUES
(1, '2026-05-04 08:00', '2026-05-04 08:30', TRUE),
(1, '2026-05-04 09:00', '2026-05-04 09:30', TRUE),
(1, '2026-05-04 10:00', '2026-05-04 10:30', TRUE),

(2, '2026-05-04 08:30', '2026-05-04 09:00', TRUE),
(2, '2026-05-04 09:30', '2026-05-04 10:00', TRUE),

(3, '2026-05-05 08:00', '2026-05-05 08:30', TRUE),
(3, '2026-05-05 09:00', '2026-05-05 09:30', TRUE),

(4, '2026-05-05 10:00', '2026-05-05 10:30', TRUE),

(5, '2026-05-06 08:00', '2026-05-06 08:30', TRUE),
(5, '2026-05-06 09:00', '2026-05-06 09:30', TRUE),

(6, '2026-05-06 10:00', '2026-05-06 10:30', TRUE),

(7, '2026-05-07 08:00', '2026-05-07 08:30', TRUE),
(8, '2026-05-07 09:00', '2026-05-07 09:30', TRUE),
(9, '2026-05-08 10:00', '2026-05-08 10:30', TRUE);